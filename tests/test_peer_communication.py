from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import utils.peer_communication as peer
from main_loop import (
    CANONICAL_BOOTSTRAP_README_SHA256,
    ROLLOUT_SYSTEM_INSTRUCTIONS_CAPABILITY_NAME,
    ROLLOUT_SYSTEM_INSTRUCTIONS_FINGERPRINT,
    ROLLOUT_SYSTEM_INSTRUCTIONS_MODE,
    ROLLOUT_SYSTEM_INSTRUCTIONS_VERSION,
    _claim_runtime_benchmark,
    _format_runtime_markdown,
    _peer_communication_resume_compatible,
    _record_current_peer_communication_capability,
    canonical_rollout_system_instructions,
    run_child_tool_handler,
    run_worker,
)
from utils.benchmark_driver import RolloutBenchmark
from utils.codex_runner import runner_binary_path, run_codex_rollout
from utils.openrouter import call_openrouter_with_tools
from utils.peer_communication import (
    BATCH_MESSAGE_LIMIT,
    DEFAULT_PEER_ROLLOUT_COUNT,
    DELIVERY_ACK_TOOL_NAME,
    DELIVERY_ACK_BOUNDARY_TOOL_NAME,
    DELIVERY_CLAIM_TOOL_NAME,
    DELIVERY_CYCLE_STARTED_TOOL_NAME,
    DELIVERY_MAX_BYTES,
    DELIVERY_MAX_MESSAGES,
    DELIVERY_PREPARE_TOOL_NAME,
    LEGACY_AUTOMATIC_DELIVERY_FINGERPRINT,
    LEGACY_AUTOMATIC_DELIVERY_VERSION,
    LEGACY_DISTINCT_NAMES_FINGERPRINT,
    LEGACY_DISTINCT_NAMES_VERSION,
    LEGACY_PEER_COMMUNICATION_FINGERPRINT,
    LEGACY_PEER_COMMUNICATION_TOOL_NAME,
    LEGACY_TWO_TOOL_FINGERPRINT,
    PEER_COMMUNICATION_CAPABILITY_NAME,
    PEER_COMMUNICATION_FINGERPRINT,
    PEER_COMMUNICATION_VERSION,
    SAFE_ENGLISH_FIRST_NAMES,
    SEND_MESSAGE_INPUT_SCHEMA,
    SEND_MESSAGE_TOOL_NAME,
    SUPPORTED_PEER_ROLLOUT_COUNTS,
    PeerCommunicationBridge,
    PeerCommunicationScope,
    PeerCommunicationStore,
    forward_peer_message_tool,
    peer_communication_handler_command,
    peer_communication_openrouter_tools,
)


TEST_NAMES = tuple(SAFE_ENGLISH_FIRST_NAMES[:DEFAULT_PEER_ROLLOUT_COUNT])
TEST_MAPPING = dict(enumerate(TEST_NAMES))


def scope(
    benchmark: str = "open-ended",
    task_index: int = 24,
    batch_id: str | None = None,
    population_size: int = DEFAULT_PEER_ROLLOUT_COUNT,
) -> PeerCommunicationScope:
    return PeerCommunicationScope(
        benchmark=benchmark,
        generation=0,
        seed=42,
        task_index=task_index,
        task_id=f"batch_{task_index}",
        batch_id=batch_id or f"supervisor-batch-{task_index}",
        population_size=population_size,
    )


def send(store: PeerCommunicationStore, sender: int, receiver: str, message: str, **extra):
    return store.handle(
        sender,
        SEND_MESSAGE_TOOL_NAME,
        {"message": message, "receiver": receiver, **extra},
    )


class PeerCommunicationTests(unittest.TestCase):
    def make_store(
        self,
        root: Path,
        *,
        benchmark: str = "open-ended",
        task_index: int = 24,
        batch_id: str | None = None,
        mapping: dict[int, str] | None = TEST_MAPPING,
        population_size: int = DEFAULT_PEER_ROLLOUT_COUNT,
        callback=None,
    ) -> PeerCommunicationStore:
        return PeerCommunicationStore(
            root / f"task_{task_index:06d}" / f"batch_{batch_id or task_index}",
            scope(benchmark, task_index, batch_id, population_size),
            name_mapping=mapping,
            lifecycle_callback=callback,
        )

    def test_random_unique_name_assignment_for_supported_populations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for population_size in sorted(SUPPORTED_PEER_ROLLOUT_COUNTS):
                expected_names = tuple(
                    SAFE_ENGLISH_FIRST_NAMES[:population_size]
                )
                with patch.object(
                    peer.secrets.SystemRandom,
                    "sample",
                    return_value=list(expected_names),
                ) as sample:
                    store = self.make_store(
                        root / str(population_size),
                        mapping=None,
                        population_size=population_size,
                    )
                sample.assert_called_once_with(
                    list(SAFE_ENGLISH_FIRST_NAMES), population_size
                )
                self.assertEqual(store.roster, expected_names)
                self.assertEqual(len(set(store.roster)), population_size)
                self.assertEqual(
                    len({name[0].casefold() for name in store.roster}),
                    population_size,
                )
                self.assertTrue(
                    set(store.roster) <= set(SAFE_ENGLISH_FIRST_NAMES)
                )
            bad_scope = PeerCommunicationScope(
                **{**scope().metadata(), "population_size": 7}
            )
            with self.assertRaisesRegex(ValueError, "one of: 8, 16"):
                PeerCommunicationStore(root / "bad", bad_scope)

        for population_size in sorted(SUPPORTED_PEER_ROLLOUT_COUNTS):
            for _ in range(256):
                mapping = PeerCommunicationStore.random_name_mapping(
                    population_size
                )
                names = tuple(
                    mapping[index] for index in range(population_size)
                )
                self.assertEqual(
                    len({name[0].casefold() for name in names}),
                    population_size,
                )

        roster = set(SAFE_ENGLISH_FIRST_NAMES)
        for confusing_pair in (
            {"Sofia", "Sophia"},
            {"Sara", "Sarah"},
            {"Sean", "Shawn"},
            {"Steven", "Stephen"},
        ):
            self.assertFalse(confusing_pair <= roster)

    def test_name_mapping_persists_exactly_and_resume_rejects_change_or_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = self.make_store(root)
            manifest = json.loads((store.log_dir / "manifest.json").read_text())
            self.assertEqual(
                manifest["name_mapping"],
                {str(index): name for index, name in TEST_MAPPING.items()},
            )
            resumed = self.make_store(root, mapping=None)
            self.assertEqual(resumed.name_mapping, TEST_MAPPING)
            changed = {**TEST_MAPPING, 0: SAFE_ENGLISH_FIRST_NAMES[8]}
            with self.assertRaisesRegex(RuntimeError, "changed during resume"):
                self.make_store(root, mapping=changed)
            duplicate = {**TEST_MAPPING, 1: TEST_MAPPING[0]}
            with self.assertRaisesRegex(RuntimeError, "distinct safe"):
                self.make_store(Path(temp) / "duplicate", task_index=25, mapping=duplicate)

            invalid_partial = Path(temp) / "invalid-partial"
            invalid_store = self.make_store(invalid_partial, task_index=26)
            manifest_path = invalid_store.log_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["name_mapping"]["1"] = "Amelia"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(
                peer,
                "SAFE_ENGLISH_FIRST_NAMES",
                (*SAFE_ENGLISH_FIRST_NAMES, "Amelia"),
            ), self.assertRaisesRegex(RuntimeError, "distinct initials"):
                self.make_store(invalid_partial, task_index=26, mapping=None)

            names_16 = tuple(SAFE_ENGLISH_FIRST_NAMES[:16])
            mapping_16 = dict(enumerate(names_16))
            store_16 = self.make_store(
                root / "sixteen",
                task_index=27,
                mapping=mapping_16,
                population_size=16,
            )
            manifest_16 = json.loads(
                (store_16.log_dir / "manifest.json").read_text()
            )
            self.assertEqual(
                manifest_16["name_mapping"],
                {str(index): name for index, name in mapping_16.items()},
            )
            resumed_16 = self.make_store(
                root / "sixteen",
                task_index=27,
                mapping=None,
                population_size=16,
            )
            self.assertEqual(resumed_16.name_mapping, mapping_16)

    def test_schema_and_runtime_expose_only_named_direct_send(self) -> None:
        tools = peer_communication_openrouter_tools()
        neutral_description = (
            "Send a bounded non-empty UTF-8 direct message to a named peer in the current batch. "
            "The receiver must exactly match a peer name in runtime.md. Delivery is automatic "
            "at a subsequent supported inference boundary."
        )
        self.assertEqual([tool["name"] for tool in tools], [SEND_MESSAGE_TOOL_NAME])
        self.assertEqual(tools[0]["description"], neutral_description)
        self.assertEqual(tools[0]["parameters"], SEND_MESSAGE_INPUT_SCHEMA)
        self.assertEqual(set(SEND_MESSAGE_INPUT_SCHEMA["properties"]), {"message", "receiver"})
        self.assertEqual(SEND_MESSAGE_INPUT_SCHEMA["required"], ["message", "receiver"])
        self.assertFalse(SEND_MESSAGE_INPUT_SCHEMA["additionalProperties"])
        self.assertEqual(
            SEND_MESSAGE_INPUT_SCHEMA["properties"]["message"]["description"],
            "A bounded non-empty UTF-8 message (maximum 2048 bytes).",
        )
        self.assertEqual(
            SEND_MESSAGE_INPUT_SCHEMA["properties"]["receiver"]["description"],
            "The exact peer name listed in runtime.md.",
        )
        serialized = json.dumps(tools)
        for forbidden in (
            "read_messages",
            LEGACY_PEER_COMMUNICATION_TOOL_NAME,
            "topic",
            "recipient_rollout_index",
            "after_id",
            '"action"',
        ):
            self.assertNotIn(forbidden, serialized)
        names_16 = tuple(SAFE_ENGLISH_FIRST_NAMES[:16])
        runtime = _format_runtime_markdown(
            instance_uuid="instance",
            has_problem_pool=False,
            peer_name=names_16[0],
            peer_roster=names_16,
        )
        peer_section = "## Peer Identity" + runtime.split("## Peer Identity", 1)[1]
        self.assertEqual(
            [line for line in peer_section.splitlines() if line],
            [
                "## Peer Identity",
                f"- your name: {names_16[0]}",
                f"- other peer names: {', '.join(names_16[1:])}",
            ],
        )
        for forbidden in (
            "send_message",
            "delivery",
            "polling",
            "inference",
            "collaborative",
            "optional",
            "scoring",
        ):
            self.assertNotIn(forbidden, peer_section.casefold())
        bootstrap = (
            Path(__file__).resolve().parents[1] / "seeds/bootstrap/README.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(bootstrap, canonical_rollout_system_instructions())
        self.assertEqual(
            hashlib.sha256(bootstrap.encode()).hexdigest(),
            CANONICAL_BOOTSTRAP_README_SHA256,
        )
        bootstrap_words = " ".join(bootstrap.split())
        self.assertIn("## The others", bootstrap)
        self.assertIn('send_message(message="...", receiver="...")', bootstrap)
        self.assertIn(
            "`receiver` must exactly match one of the names in `runtime.md`.",
            bootstrap_words,
        )
        for prescriptive in (
            "claiming a direction",
            "sharing a result",
            "environment state",
            "requesting verification",
            "warning of a conflict",
            "divide complementary",
            "intermediate findings",
            "targeted questions",
            "critique",
            "verify work",
            "synthesize",
            "conflicting or duplicate",
            "communication is optional",
        ):
            self.assertNotIn(prescriptive, serialized.casefold())

    def test_unknown_self_and_removed_interfaces_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(Path(temp))
            self.assertEqual(send(store, 0, "Unknown", "x")["error_code"], "unknown_receiver")
            self.assertEqual(send(store, 0, TEST_NAMES[0], "x")["error_code"], "self_receiver")
            for arguments in (
                {"message": "x", "receiver": TEST_NAMES[1], "topic": "legacy"},
                {"message": "x", "receiver": TEST_NAMES[1], "recipient_rollout_index": 1},
                {"message": "x", "receiver": TEST_NAMES[1], "action": "send"},
            ):
                self.assertEqual(
                    store.handle(0, SEND_MESSAGE_TOOL_NAME, arguments)["error_code"],
                    "unsupported_arguments",
                )
            for tool in ("read_messages", LEGACY_PEER_COMMUNICATION_TOOL_NAME):
                self.assertEqual(store.handle(0, tool, {})["error_code"], "unsupported_dynamic_tool")

    def test_direct_delivery_sender_forgery_and_bridge_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(Path(temp))
            forged = send(
                store,
                0,
                TEST_NAMES[1],
                "x",
                sender_name=TEST_NAMES[7],
            )
            self.assertFalse(forged["success"])
            with PeerCommunicationBridge(store) as bridge:
                credentials = bridge.credentials(3)
                result = forward_peer_message_tool(
                    credentials.endpoint,
                    credentials.token,
                    {
                        "tool": SEND_MESSAGE_TOOL_NAME,
                        "namespace": None,
                        "arguments": {
                            "message": "owned by token",
                            "receiver": TEST_NAMES[1],
                        },
                    },
                )
                self.assertTrue(result["success"])
                self.assertNotIn("sender_rollout_index", result)
                self.assertNotIn("recipient_rollout_index", result)
                rejected = forward_peer_message_tool(
                    credentials.endpoint,
                    "wrong-token",
                    {
                        "tool": DELIVERY_PREPARE_TOOL_NAME,
                        "namespace": None,
                        "arguments": {},
                    },
                )
                self.assertEqual(
                    rejected["error_code"],
                    "peer_communication_authentication_failed",
                )
            unavailable = forward_peer_message_tool(
                "http://127.0.0.1:1/peer-communication",
                "test-token",
                {
                    "tool": DELIVERY_PREPARE_TOOL_NAME,
                    "namespace": None,
                    "arguments": {},
                },
            )
            self.assertEqual(
                unavailable["error_code"],
                "peer_communication_transport_unavailable",
            )
            record = json.loads((store.records_dir / "000000001.json").read_text())
            self.assertEqual(record["sender_rollout_index"], 3)
            self.assertEqual(record["sender_name"], TEST_NAMES[3])
            self.assertEqual(stat.S_IMODE(store.log_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(store.records_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(store.deliveries_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((store.log_dir / "manifest.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((store.records_dir / "000000001.json").stat().st_mode), 0o600)

    def test_direct_visibility_ordering_cursor_ack_and_retry_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = self.make_store(root)
            self.assertFalse(store.prepare_delivery(1)["pending"])
            send(store, 0, TEST_NAMES[1], "first")
            send(store, 2, TEST_NAMES[3], "not yours")
            send(store, 4, TEST_NAMES[1], "second")
            self.assertFalse(store.prepare_delivery(0)["pending"])
            prepared = store.prepare_delivery(1)
            self.assertTrue(prepared["pending"])
            self.assertEqual(prepared["message_count"], 2)
            self.assertLess(prepared["injection"].index("Message #1"), prepared["injection"].index("Message #3"))
            self.assertIn(f"from {TEST_NAMES[0]}", prepared["injection"])
            self.assertIn("UNTRUSTED PEER CONTENT", prepared["injection"])
            retried = store.prepare_delivery(1)
            self.assertEqual(retried["delivery_id"], prepared["delivery_id"])
            self.assertEqual(retried["injection"], prepared["injection"])

            interrupted = self.make_store(root, mapping=None)
            after_restart = interrupted.prepare_delivery(1)
            self.assertEqual(after_restart["delivery_id"], prepared["delivery_id"])
            acknowledged = interrupted.acknowledge_delivery(1, prepared["delivery_id"])
            self.assertTrue(acknowledged["committed"])
            self.assertFalse(interrupted.prepare_delivery(1)["pending"])
            duplicate_ack = interrupted.acknowledge_delivery(1, prepared["delivery_id"])
            self.assertTrue(duplicate_ack["already_committed"])
            resumed_again = self.make_store(root, mapping=None)
            self.assertFalse(resumed_again.prepare_delivery(1)["pending"])

    def test_post_tool_cycle_claim_is_atomic_persisted_and_acknowledged_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = self.make_store(root)
            send(store, 0, TEST_NAMES[1], "between tool cycles")

            first = store.claim_tool_cycle_delivery(1, "tool-call-a")
            self.assertTrue(first["pending"])
            self.assertIn("between tool cycles", first["injection"])
            parallel = store.claim_tool_cycle_delivery(1, "tool-call-b")
            self.assertFalse(parallel["pending"])
            self.assertTrue(parallel["cycle_claimed"])

            resumed = self.make_store(root, mapping=None)
            retried = resumed.claim_tool_cycle_delivery(1, "tool-call-a")
            self.assertEqual(retried["delivery_id"], first["delivery_id"])
            self.assertFalse(
                resumed.acknowledge_tool_cycle_delivery(1, "tool-call-b")["matched"]
            )
            acknowledged = resumed.acknowledge_tool_cycle_delivery(1, "tool-call-a")
            self.assertTrue(acknowledged["matched"])
            self.assertTrue(acknowledged["committed"])
            repeated = resumed.acknowledge_tool_cycle_delivery(1, "tool-call-a")
            self.assertTrue(repeated["already_committed"])
            self.assertFalse(resumed.claim_tool_cycle_delivery(1, "tool-call-b")["pending"])
            self.assertTrue(resumed.start_next_tool_cycle(1)["opened"])

            send(resumed, 2, TEST_NAMES[1], "next sampling cycle")
            second = resumed.claim_tool_cycle_delivery(1, "tool-call-b")
            self.assertTrue(second["pending"])
            self.assertNotEqual(second["delivery_id"], first["delivery_id"])

            # A restart before engine acceptance recovers the same durable
            # lease through the initial-inference path and clears the stale
            # tool-cycle claim only when that injection is acknowledged.
            interrupted = self.make_store(root, mapping=None)
            initial = interrupted.prepare_delivery(1)
            self.assertEqual(initial["delivery_id"], second["delivery_id"])
            interrupted.acknowledge_delivery(1, initial["delivery_id"])
            self.assertFalse(interrupted.prepare_delivery(1)["pending"])

    def test_internal_tool_cycle_operations_route_only_through_authenticated_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(Path(temp))
            send(store, 0, TEST_NAMES[1], "bridge cycle")
            with PeerCommunicationBridge(store) as bridge:
                credentials = bridge.credentials(1)
                claimed = forward_peer_message_tool(
                    credentials.endpoint,
                    credentials.token,
                    {
                        "tool": DELIVERY_CLAIM_TOOL_NAME,
                        "namespace": None,
                        "arguments": {"boundary_id": "bridge-tool"},
                    },
                )
                self.assertTrue(claimed["pending"])
                acknowledged = forward_peer_message_tool(
                    credentials.endpoint,
                    credentials.token,
                    {
                        "tool": DELIVERY_ACK_BOUNDARY_TOOL_NAME,
                        "namespace": None,
                        "arguments": {"boundary_id": "bridge-tool"},
                    },
                )
                self.assertTrue(acknowledged["committed"])
                opened = forward_peer_message_tool(
                    credentials.endpoint,
                    credentials.token,
                    {
                        "tool": DELIVERY_CYCLE_STARTED_TOOL_NAME,
                        "namespace": None,
                        "arguments": {},
                    },
                )
                self.assertTrue(opened["opened"])

    def test_delayed_late_and_bounded_backlog_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = self.make_store(Path(temp))
            self.assertFalse(store.prepare_delivery(1)["pending"])
            send(store, 0, TEST_NAMES[1], "arrived during generation")
            delayed = store.prepare_delivery(1)
            self.assertIn("arrived during generation", delayed["injection"])
            store.acknowledge_delivery(1, delayed["delivery_id"])

            for index in range(DELIVERY_MAX_MESSAGES + 3):
                send(store, 2, TEST_NAMES[1], f"backlog-{index}-" + "x" * 1200)
            first = store.prepare_delivery(1)
            self.assertLessEqual(first["message_count"], DELIVERY_MAX_MESSAGES)
            self.assertLessEqual(len(first["injection"].encode()), DELIVERY_MAX_BYTES)
            self.assertTrue(first["has_more"])
            store.acknowledge_delivery(1, first["delivery_id"])
            second = store.prepare_delivery(1)
            self.assertTrue(second["pending"])
            store.acknowledge_delivery(1, second["delivery_id"])
            self.assertFalse(store.prepare_delivery(1)["pending"])

            send(store, 3, TEST_NAMES[1], "late after final inference")
            late_cursor = json.loads(store._cursor_path(1).read_text())["through_id"]
            resumed = self.make_store(Path(temp), mapping=None)
            self.assertEqual(json.loads(resumed._cursor_path(1).read_text())["through_id"], late_cursor)
            self.assertIn("late after final inference", resumed.prepare_delivery(1)["injection"])

    def test_validation_caps_concurrency_and_progress_redaction(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        with tempfile.TemporaryDirectory() as temp:
            names_16 = tuple(SAFE_ENGLISH_FIRST_NAMES[:16])
            store = self.make_store(
                Path(temp),
                mapping=dict(enumerate(names_16)),
                population_size=16,
                callback=lambda event, fields: events.append((event, fields)),
            )
            for message, code in (
                ("", "invalid_message"),
                ("   ", "invalid_message"),
                ("bad\x00control", "invalid_message_controls"),
                ("🙂" * 513, "message_too_large"),
            ):
                self.assertEqual(
                    send(store, 0, names_16[1], message)["error_code"], code
                )
            barrier = threading.Barrier(16)

            def sender(index: int) -> list[int]:
                barrier.wait()
                receiver = names_16[(index + 1) % 16]
                return [
                    send(store, index, receiver, f"secret-{index}:{offset}")[
                        "id"
                    ]
                    for offset in range(10)
                ]

            with ThreadPoolExecutor(max_workers=16) as executor:
                ids = [
                    item
                    for result in executor.map(sender, range(16))
                    for item in result
                ]
            self.assertEqual(sorted(ids), list(range(1, 161)))
            lifecycle = json.dumps(events)
            self.assertNotIn("secret-", lifecycle)
            self.assertEqual(store.message_count, 160)
            self.assertEqual(store.batch_message_limit, BATCH_MESSAGE_LIMIT)

            delivery_barrier = threading.Barrier(16)

            def deliver(index: int) -> int:
                delivery_barrier.wait()
                prepared = store.prepare_delivery(index)
                self.assertTrue(prepared["pending"])
                self.assertEqual(prepared["message_count"], 8)
                acknowledged = store.acknowledge_delivery(
                    index, prepared["delivery_id"]
                )
                self.assertTrue(acknowledged["committed"])
                second = store.prepare_delivery(index)
                self.assertTrue(second["pending"])
                self.assertEqual(second["message_count"], 2)
                store.acknowledge_delivery(index, second["delivery_id"])
                self.assertFalse(store.prepare_delivery(index)["pending"])
                return prepared["message_count"] + second["message_count"]

            with ThreadPoolExecutor(max_workers=16) as executor:
                delivered_counts = list(executor.map(deliver, range(16)))
            self.assertEqual(delivered_counts, [10] * 16)

        with tempfile.TemporaryDirectory() as temp, patch.object(peer, "PER_ROLLOUT_SEND_LIMIT", 2), patch.object(peer, "BATCH_MESSAGE_LIMIT", 3):
            store = self.make_store(Path(temp))
            self.assertTrue(send(store, 0, TEST_NAMES[1], "one")["success"])
            self.assertTrue(send(store, 0, TEST_NAMES[1], "two")["success"])
            self.assertEqual(send(store, 0, TEST_NAMES[1], "three")["error_code"], "rollout_send_limit_reached")
            self.assertTrue(send(store, 1, TEST_NAMES[2], "batch third")["success"])
            self.assertEqual(send(store, 2, TEST_NAMES[3], "batch over")["error_code"], "batch_message_limit_reached")

        with tempfile.TemporaryDirectory() as temp:
            store_8 = self.make_store(Path(temp) / "eight")
            store_16 = self.make_store(
                Path(temp) / "sixteen",
                mapping=dict(enumerate(SAFE_ENGLISH_FIRST_NAMES[:16])),
                population_size=16,
            )
            self.assertEqual(store_8.batch_message_limit, 512)
            self.assertEqual(store_16.batch_message_limit, 1_024)

    def test_cross_batch_isolation_and_capability_resume_versioning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self.make_store(root, task_index=24, batch_id="first")
            send(first, 0, TEST_NAMES[1], "task 24")
            resumed = self.make_store(root, task_index=24, batch_id="first", mapping=None)
            self.assertIn("task 24", resumed.prepare_delivery(1)["injection"])
            second = self.make_store(root, task_index=24, batch_id="second")
            self.assertFalse(second.prepare_delivery(1)["pending"])
            third = self.make_store(root, task_index=25, batch_id="third")
            self.assertFalse(third.prepare_delivery(1)["pending"])
            names_16 = tuple(SAFE_ENGLISH_FIRST_NAMES[:16])
            sixteen = self.make_store(
                root,
                task_index=24,
                batch_id="sixteen",
                mapping=dict(enumerate(names_16)),
                population_size=16,
            )
            self.assertFalse(sixteen.prepare_delivery(1)["pending"])

            current = {
                "peer_communication_enabled": True,
                "peer_communication_version": PEER_COMMUNICATION_VERSION,
                "peer_communication_fingerprint": PEER_COMMUNICATION_FINGERPRINT,
                "peer_communication_batch_id": "batch-current",
                "peer_communication_population_size": 8,
            }
            self.assertTrue(_peer_communication_resume_compatible({}, require_fingerprint=False))
            self.assertFalse(_peer_communication_resume_compatible({}, require_fingerprint=True))
            self.assertTrue(
                _peer_communication_resume_compatible(
                    current, require_fingerprint=True, population_size=8
                )
            )
            self.assertFalse(
                _peer_communication_resume_compatible(
                    current, require_fingerprint=True, population_size=16
                )
            )
            for version, fingerprint in (
                (1, LEGACY_PEER_COMMUNICATION_FINGERPRINT),
                (2, LEGACY_TWO_TOOL_FINGERPRINT),
                (
                    LEGACY_AUTOMATIC_DELIVERY_VERSION,
                    LEGACY_AUTOMATIC_DELIVERY_FINGERPRINT,
                ),
                (
                    LEGACY_DISTINCT_NAMES_VERSION,
                    LEGACY_DISTINCT_NAMES_FINGERPRINT,
                ),
            ):
                legacy = {
                    **current,
                    "peer_communication_version": version,
                    "peer_communication_fingerprint": fingerprint,
                }
                self.assertFalse(_peer_communication_resume_compatible(legacy, require_fingerprint=True))

            identity_root = root / "identity"
            identity_root.mkdir()
            identity_path = identity_root / "runtime_benchmark.json"
            identity_path.write_text(json.dumps({"format": "metalanguage-runtime-benchmark", "version": 1, "benchmark": "open-ended"}))
            _claim_runtime_benchmark(identity_root, "open-ended")
            _record_current_peer_communication_capability(identity_root)
            capability = json.loads(identity_path.read_text())["capabilities"][PEER_COMMUNICATION_CAPABILITY_NAME]
            self.assertEqual(capability["version"], PEER_COMMUNICATION_VERSION)
            instruction_capability = json.loads(identity_path.read_text())[
                "capabilities"
            ][ROLLOUT_SYSTEM_INSTRUCTIONS_CAPABILITY_NAME]
            self.assertEqual(
                instruction_capability,
                {
                    "enabled": True,
                    "version": ROLLOUT_SYSTEM_INSTRUCTIONS_VERSION,
                    "fingerprint": ROLLOUT_SYSTEM_INSTRUCTIONS_FINGERPRINT,
                    "mode": ROLLOUT_SYSTEM_INSTRUCTIONS_MODE,
                    "sha256": CANONICAL_BOOTSTRAP_README_SHA256,
                },
            )
            identity = json.loads(identity_path.read_text())
            identity["capabilities"][PEER_COMMUNICATION_CAPABILITY_NAME] = {
                "enabled": True,
                "version": LEGACY_DISTINCT_NAMES_VERSION,
                "fingerprint": LEGACY_DISTINCT_NAMES_FINGERPRINT,
            }
            identity_path.write_text(json.dumps(identity))
            _claim_runtime_benchmark(identity_root, "open-ended")
            still_legacy = json.loads(identity_path.read_text())["capabilities"][PEER_COMMUNICATION_CAPABILITY_NAME]
            self.assertEqual(still_legacy["version"], LEGACY_DISTINCT_NAMES_VERSION)
            _record_current_peer_communication_capability(identity_root)
            upgraded = json.loads(identity_path.read_text())["capabilities"][PEER_COMMUNICATION_CAPABILITY_NAME]
            self.assertEqual(upgraded["version"], PEER_COMMUNICATION_VERSION)

    def test_all_benchmarks_and_openrouter_use_only_send_with_automatic_delivery(self) -> None:
        class Driver:
            def handle_tool(self, *_args):
                return None

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("work", "seed", "archive", "shared", "state"):
                (root / name).mkdir()
            for index, benchmark in enumerate(("open-ended", "supergpqa", "arc-agi")):
                captured: list[dict[str, object]] = []
                store = self.make_store(root / "bus", benchmark=benchmark, task_index=index)
                send(store, 0, TEST_NAMES[1], f"{benchmark} initial")

                def response(**kwargs):
                    captured.append(kwargs)
                    if len(captured) == 1:
                        send(store, 3, TEST_NAMES[1], f"{benchmark} delayed")
                        return {
                            "output": [{
                                "type": "function_call",
                                "id": "send-item",
                                "call_id": "send-call",
                                "name": SEND_MESSAGE_TOOL_NAME,
                                "arguments": json.dumps({"message": "routed result", "receiver": TEST_NAMES[2]}),
                            }]
                        }
                    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "finished"}]}]}

                with self.subTest(benchmark=benchmark), patch("main_loop.call_openrouter_with_tools", side_effect=response):
                    result = run_worker(
                        api_key="offline",
                        model="fixture/model",
                        workdir=root / "work",
                        seed_output_dir=root / "seed",
                        archive_repo_dir=root / "archive",
                        shared_workspace_dir=root / "shared",
                        worker_state_dir=root / "state",
                        shared_workspace_write_log=root / "writes.jsonl",
                        shared_workspace_lock=threading.Lock(),
                        task_index=index,
                        task_id=f"task-{index}",
                        rollout_index=1,
                        rollout_username="rollout_user_001",
                        timeout_seconds=5,
                        bash_timeout_seconds=1,
                        openrouter_max_retries=0,
                        continuation_context={},
                        benchmark_driver=Driver(),
                        rollout_benchmark=RolloutBenchmark(context={}, model_metadata={"tools": []}),
                        peer_communication_store=store,
                        initial_user_text="test",
                        instructions=canonical_rollout_system_instructions(),
                    )
                self.assertEqual(result.status, "completed")
                self.assertTrue(
                    all(
                        call["instructions"]
                        == canonical_rollout_system_instructions()
                        for call in captured
                    )
                )
                tools = {tool["name"]: tool for tool in captured[0]["tools"]}
                self.assertEqual(set(tools) & {SEND_MESSAGE_TOOL_NAME, "read_messages", LEGACY_PEER_COMMUNICATION_TOOL_NAME}, {SEND_MESSAGE_TOOL_NAME})
                self.assertEqual(tools[SEND_MESSAGE_TOOL_NAME]["parameters"], SEND_MESSAGE_INPUT_SCHEMA)
                first_input = json.dumps(captured[0]["input_items"])
                second_input = json.dumps(captured[1]["input_items"])
                self.assertIn(f"{benchmark} initial", first_input)
                self.assertIn(f"{benchmark} delayed", second_input)
                self.assertIn("UNTRUSTED PEER CONTENT", first_input)
                self.assertFalse(store.prepare_delivery(1)["pending"])
                recipient = store.prepare_delivery(2)
                self.assertIn("routed result", recipient["injection"])

    def test_openrouter_request_uses_top_level_canonical_instructions(self) -> None:
        class Response:
            ok = True

            @staticmethod
            def json() -> dict[str, object]:
                return {"output": []}

        canonical = canonical_rollout_system_instructions()
        with patch("utils.openrouter.requests.post", return_value=Response()) as post:
            response = call_openrouter_with_tools(
                api_key="offline",
                model="fixture/model",
                instructions=canonical,
                input_items=[
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Begin."}],
                    }
                ],
                max_retries=0,
            )
        self.assertEqual(response, {"output": []})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["instructions"], canonical)
        self.assertEqual(
            hashlib.sha256(payload["instructions"].encode()).hexdigest(),
            CANONICAL_BOOTSTRAP_README_SHA256,
        )
        self.assertEqual(payload["input"][0]["role"], "user")
        self.assertEqual(payload["input"][0]["content"][0]["text"], "Begin.")

    def test_codex_request_and_central_handler_support_send_and_internal_delivery_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("work", "state", "codex-home", "seed", "archive", "shared"):
                (root / name).mkdir()
            context = root / "control-context.json"
            context.write_text(
                json.dumps(
                    {
                        "peer_communication_endpoint": "http://127.0.0.1:1",
                        "peer_communication_token": "test-only-token",
                    }
                )
            )
            result = run_codex_rollout(
                runner_bin=Path("/bin/cat"),
                model="fixture/model",
                workdir=root / "work",
                control_dir=root / "control",
                worker_state_dir=root / "state",
                codex_home=root / "codex-home",
                seed_output_dir=root / "seed",
                archive_repo_dir=root / "archive",
                archive_git_dir=None,
                shared_workspace_dir=root / "shared",
                rollout_username="rollout_user_000",
                timeout_seconds=2,
                initial_user_text="Begin.",
                base_instructions=canonical_rollout_system_instructions(),
                spawn_child_handler_context_path=context,
            )
            request = json.loads(Path(result["request_path"]).read_text())
            self.assertEqual(
                request["base_instructions"],
                canonical_rollout_system_instructions(),
            )
            self.assertEqual(
                hashlib.sha256(request["base_instructions"].encode()).hexdigest(),
                CANONICAL_BOOTSTRAP_README_SHA256,
            )
            self.assertNotEqual(
                request["peer_communication_handler_command"],
                request["spawn_child_handler_command"],
            )
            self.assertIn("main_loop.py", request["spawn_child_handler_command"][1])
            self.assertTrue(
                request["peer_communication_handler_command"][1].endswith(
                    "utils/peer_communication.py"
                )
            )
            self.assertEqual(
                request["peer_communication_handler_command"][2],
                "--supervisor-handler",
            )

            store = self.make_store(root / "bus")
            with PeerCommunicationBridge(store) as bridge:
                sender = bridge.credentials(5)
                recipient = bridge.credentials(1)
                context.write_text(json.dumps({"peer_communication_endpoint": sender.endpoint, "peer_communication_token": sender.token}))
                send_payload = {
                    "tool": SEND_MESSAGE_TOOL_NAME,
                    "namespace": None,
                    "call_id": "call",
                    "arguments": {"message": "central callback", "receiver": TEST_NAMES[1]},
                }
                stdout = io.StringIO()
                with patch("sys.stdin", io.StringIO(json.dumps(send_payload))), patch("sys.stdout", stdout):
                    run_child_tool_handler(context)
                accepted = json.loads(stdout.getvalue())
                self.assertEqual(set(accepted), {"success", "tool", "accepted", "durable", "id", "receiver"})

                context.write_text(json.dumps({"peer_communication_endpoint": recipient.endpoint, "peer_communication_token": recipient.token}))
                prepare_payload = {"tool": DELIVERY_PREPARE_TOOL_NAME, "namespace": None, "arguments": {}}
                stdout = io.StringIO()
                with patch("sys.stdin", io.StringIO(json.dumps(prepare_payload))), patch("sys.stdout", stdout):
                    run_child_tool_handler(context)
                prepared = json.loads(stdout.getvalue())
                self.assertIn("central callback", prepared["injection"])
                ack_payload = {"tool": DELIVERY_ACK_TOOL_NAME, "namespace": None, "arguments": {"delivery_id": prepared["delivery_id"]}}
                stdout = io.StringIO()
                with patch("sys.stdin", io.StringIO(json.dumps(ack_payload))), patch("sys.stdout", stdout):
                    run_child_tool_handler(context)
                self.assertTrue(json.loads(stdout.getvalue())["committed"])

    @unittest.skipUnless(runner_binary_path().is_file(), "built Codex runner is required")
    def test_actual_codex_runner_eight_way_peer_delivery_production_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = self.make_store(root / "bus")
            runner = runner_binary_path()
            with PeerCommunicationBridge(store) as bridge:
                contexts: list[Path] = []
                commands: list[list[str]] = []
                tokens: list[str] = []
                for rollout_index in range(DEFAULT_PEER_ROLLOUT_COUNT):
                    credentials = bridge.credentials(rollout_index)
                    tokens.append(credentials.token)
                    context = root / f"context-{rollout_index}.json"
                    context.write_text(
                        json.dumps(
                            {
                                "peer_communication_endpoint": credentials.endpoint,
                                "peer_communication_token": credentials.token,
                            }
                        ),
                        encoding="utf-8",
                    )
                    context.chmod(0o600)
                    contexts.append(context)
                    commands.append(
                        peer_communication_handler_command(
                            context,
                            python_executable=sys.executable,
                        )
                    )

                barrier = threading.Barrier(DEFAULT_PEER_ROLLOUT_COUNT)

                def probe(rollout_index: int) -> subprocess.CompletedProcess[str]:
                    barrier.wait()
                    return subprocess.run(
                        [str(runner), "--peer-delivery-probe"],
                        input=json.dumps(
                            {
                                "cwd": str(root),
                                "peer_communication_handler_command": commands[rollout_index],
                            }
                        ),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env={
                            **os.environ,
                            "METALANGUAGE_TEST_PEER_DELIVERY_PROBE": "1",
                        },
                        timeout=15,
                        check=False,
                    )

                with ThreadPoolExecutor(
                    max_workers=DEFAULT_PEER_ROLLOUT_COUNT
                ) as executor:
                    results = list(
                        executor.map(probe, range(DEFAULT_PEER_ROLLOUT_COUNT))
                    )
                for result in results:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    event = json.loads(result.stdout)
                    self.assertEqual(event["event"], "peer_delivery_probe_complete")
                    self.assertFalse(event["pending"])
                    self.assertEqual(event["message_count"], 0)
                    self.assertEqual(event["payload"], {"redacted": True})
                    for token in tokens:
                        self.assertNotIn(token, result.stdout + result.stderr)

                secret_message = "private production-boundary finding"
                accepted = subprocess.run(
                    commands[0],
                    input=json.dumps(
                        {
                            "tool": SEND_MESSAGE_TOOL_NAME,
                            "namespace": None,
                            "arguments": {
                                "message": secret_message,
                                "receiver": TEST_NAMES[1],
                            },
                        }
                    ),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertTrue(json.loads(accepted.stdout)["durable"])

                delivered = subprocess.run(
                    [str(runner), "--peer-delivery-probe"],
                    input=json.dumps(
                        {
                            "cwd": str(root),
                            "peer_communication_handler_command": commands[1],
                        }
                    ),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={
                        **os.environ,
                        "METALANGUAGE_TEST_PEER_DELIVERY_PROBE": "1",
                    },
                    timeout=15,
                    check=False,
                )
                self.assertEqual(delivered.returncode, 0, delivered.stderr)
                delivery_event = json.loads(delivered.stdout)
                self.assertTrue(delivery_event["pending"])
                self.assertEqual(delivery_event["message_count"], 1)
                self.assertNotIn(secret_message, delivered.stdout + delivered.stderr)
                self.assertFalse(store.prepare_delivery(1)["pending"])

            failed = subprocess.run(
                [str(runner), "--peer-delivery-probe"],
                input=json.dumps(
                    {
                        "cwd": str(root),
                        "peer_communication_handler_command": [
                            str(root / "missing-handler")
                        ],
                    }
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    **os.environ,
                    "METALANGUAGE_TEST_PEER_DELIVERY_PROBE": "1",
                },
                timeout=5,
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            diagnostic = json.loads(failed.stdout)
            self.assertEqual(diagnostic["error_code"], "peer_delivery_prepare_failed")
            self.assertIn("failed to start", diagnostic["error_message"])
            self.assertIn("NotFound", diagnostic["error_message"])

    @unittest.skipUnless(runner_binary_path().is_file(), "built Codex runner is required")
    def test_actual_codex_post_tool_hook_injects_before_second_provider_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / "work"
            codex_home = root / "codex-home"
            work.mkdir()
            codex_home.mkdir()
            lifecycle: list[tuple[str, dict[str, object]]] = []
            store = self.make_store(
                root / "bus", callback=lambda event, fields: lifecycle.append((event, fields))
            )
            requests: list[dict[str, object]] = []
            secret = "post-tool private peer finding"

            with PeerCommunicationBridge(store) as bridge:
                sender = bridge.credentials(0)
                recipient = bridge.credentials(1)
                context = root / "recipient-context.json"
                context.write_text(
                    json.dumps(
                        {
                            "peer_communication_endpoint": recipient.endpoint,
                            "peer_communication_token": recipient.token,
                        }
                    ),
                    encoding="utf-8",
                )
                context.chmod(0o600)
                command = peer_communication_handler_command(
                    context, python_executable=sys.executable
                )

                class Provider(BaseHTTPRequestHandler):
                    def log_message(self, _format: str, *_args: object) -> None:
                        return

                    def do_GET(self) -> None:  # noqa: N802
                        body = json.dumps({"data": []}).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                    def do_POST(self) -> None:  # noqa: N802
                        length = int(self.headers.get("Content-Length", "0"))
                        payload = json.loads(self.rfile.read(length))
                        requests.append(payload)
                        response_index = len(requests)
                        if response_index == 1:
                            accepted = forward_peer_message_tool(
                                sender.endpoint,
                                sender.token,
                                {
                                    "tool": SEND_MESSAGE_TOOL_NAME,
                                    "namespace": None,
                                    "arguments": {
                                        "message": secret,
                                        "receiver": TEST_NAMES[1],
                                    },
                                },
                            )
                            if not accepted.get("success"):
                                self.send_error(500)
                                return
                            events = [
                                {"type": "response.created", "response": {"id": "resp-1"}},
                                {
                                    "type": "response.output_item.done",
                                    "item": {
                                        "type": "function_call",
                                        "call_id": "call-send-1",
                                        "name": "send_message",
                                        "arguments": json.dumps(
                                            {
                                                "message": "tool boundary",
                                                "receiver": TEST_NAMES[2],
                                            }
                                        ),
                                    },
                                },
                                {
                                    "type": "response.output_item.done",
                                    "item": {
                                        "type": "function_call",
                                        "call_id": "call-exec-1",
                                        "name": "exec_command",
                                        "arguments": json.dumps({"cmd": "pwd"}),
                                    },
                                },
                                {
                                    "type": "response.completed",
                                    "response": {
                                        "id": "resp-1",
                                        "usage": {
                                            "input_tokens": 0,
                                            "input_tokens_details": None,
                                            "output_tokens": 0,
                                            "output_tokens_details": None,
                                            "total_tokens": 0,
                                        },
                                    },
                                },
                            ]
                        else:
                            events = [
                                {"type": "response.created", "response": {"id": "resp-2"}},
                                {
                                    "type": "response.output_item.done",
                                    "item": {
                                        "type": "message",
                                        "role": "assistant",
                                        "id": "msg-final",
                                        "content": [
                                            {"type": "output_text", "text": "controlled final"}
                                        ],
                                    },
                                },
                                {
                                    "type": "response.completed",
                                    "response": {
                                        "id": "resp-2",
                                        "usage": {
                                            "input_tokens": 0,
                                            "input_tokens_details": None,
                                            "output_tokens": 0,
                                            "output_tokens_details": None,
                                            "total_tokens": 0,
                                        },
                                    },
                                },
                            ]
                        body = "".join(
                            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                            for event in events
                        ).encode()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
                provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
                provider_thread.start()
                try:
                    host, port = provider.server_address
                    (codex_home / "config.toml").write_text(
                        "model_provider = \"mock\"\n"
                        "[model_providers.mock]\n"
                        "name = \"mock\"\n"
                        f"base_url = \"http://{host}:{port}/v1\"\n"
                        "env_key = \"PATH\"\n"
                        "wire_api = \"responses\"\n",
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [str(runner_binary_path())],
                        input=json.dumps(
                            {
                                "model": "gpt-5.6-sol",
                                "cwd": str(work),
                                "codex_home": str(codex_home),
                                "initial_user_text": "Use one tool, then finish.",
                                "timeout_seconds": 30,
                                "sandbox_mode": "danger-full-access",
                                "workspace_roots": [str(work)],
                                "additional_writable_roots": [],
                                "peer_communication_handler_command": command,
                            }
                        ),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=40,
                        check=False,
                        env={**os.environ, "CODEX_HOME": str(codex_home)},
                    )
                finally:
                    provider.shutdown()
                    provider.server_close()
                    provider_thread.join(timeout=2)

                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(len(requests), 2)
                additional_tools = next(
                    item
                    for item in requests[0]["input"]
                    if item.get("type") == "additional_tools"
                )
                namespaces = {
                    tool.get("name"): tool
                    for tool in additional_tools["tools"]
                    if isinstance(tool, dict) and tool.get("type") == "namespace"
                }
                self.assertIn("functions", namespaces)
                self.assertNotIn("collaboration", namespaces)
                functions_description = json.dumps(namespaces["functions"])
                self.assertIn("### `spawn_child`", functions_description)
                self.assertIn("### `send_message`", functions_description)
                self.assertIn("message: string;", functions_description)
                self.assertIn("receiver: string;", functions_description)
                native_tools = (
                    "spawn_agent",
                    "wait_agent",
                    "list_agents",
                    "followup_task",
                    "interrupt_agent",
                    "resume_agent",
                    "close_agent",
                )
                serialized_tools = json.dumps(additional_tools)
                for native_name in native_tools:
                    self.assertNotIn(native_name, serialized_tools)
                self.assertNotIn(secret, json.dumps(requests[0]))
                self.assertIn(secret, json.dumps(requests[1]))
                self.assertIn("call-send-1", json.dumps(requests[1]))
                self.assertIn("call-exec-1", json.dumps(requests[1]))
                self.assertIn("controlled final", result.stdout)
                self.assertNotIn(secret, result.stdout + result.stderr)
                injected = [
                    json.loads(line)
                    for line in result.stdout.splitlines()
                    if line.strip()
                    and json.loads(line).get("event") == "peer_delivery_injected"
                ]
                self.assertEqual(len(injected), 1)
                self.assertEqual(injected[0]["payload"], {"redacted": True})
                self.assertEqual(
                    [event for event, _fields in lifecycle].count(
                        "peer_delivery_tool_cycle_claimed"
                    ),
                    1,
                )
                self.assertEqual(
                    [event for event, _fields in lifecycle].count(
                        "peer_delivery_committed"
                    ),
                    1,
                )
                self.assertFalse(store.prepare_delivery(1)["pending"])


if __name__ == "__main__":
    unittest.main()

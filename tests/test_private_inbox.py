from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path

from main_loop import (
    _format_runtime_markdown,
    _validate_private_inbox_partial_resume,
    persist_episode_outputs,
    run_child_tool_handler,
)
from utils.codex_runner import _handle_runner_line, run_codex_rollout
from utils.private_inbox import (
    PRIVATE_INBOX_CAPABILITY_IDENTITY,
    ROLLOUT_HUMAN_NAMES,
    cleanup_private_inboxes,
    deliver_private_message,
    initialize_private_inboxes,
    private_inbox_enabled,
)


BODY_SENTINEL = "private-body-sentinel"


class PrivateInboxTests(unittest.TestCase):
    def _root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _configs(self, root: Path, count: int = 8):
        workdirs = {}
        for index in range(count):
            workdir = root / f"rollout_{index:03d}"
            workdir.mkdir(parents=True)
            workdirs[index] = workdir
        configs = initialize_private_inboxes(
            workdirs,
            state_path=root / "private_inbox_state.json",
        )
        self.addCleanup(cleanup_private_inboxes, configs)
        return configs

    @staticmethod
    def _context(config, progress_log: Path | None = None) -> dict[str, object]:
        context: dict[str, object] = {"private_inbox": config.to_context()}
        if progress_log is not None:
            context["progress_log"] = str(progress_log)
        return context

    def test_fixed_roster_and_feature_scope(self) -> None:
        self.assertEqual(
            ROLLOUT_HUMAN_NAMES,
            (
                "Daniel",
                "Noah",
                "Elizabeth",
                "George",
                "Eva",
                "Eleanor",
                "Zoe",
                "Oliver",
            ),
        )
        self.assertTrue(private_inbox_enabled("open-ended", "codex"))
        self.assertFalse(
            private_inbox_enabled("open-ended", "codex", resolution_phase=True)
        )
        for benchmark, backend in (
            ("arc-agi", "codex"),
            ("supergpqa", "codex"),
            ("open-ended", "opencode"),
            ("open-ended", "openrouter"),
            ("arc-agi", "opencode"),
            ("supergpqa", "openrouter"),
        ):
            self.assertFalse(private_inbox_enabled(benchmark, backend))

    def test_schema_equivalent_validation_rejects_spoof_path_self_and_broadcast(self) -> None:
        root = self._root()
        configs = self._configs(root, 3)
        context = self._context(configs[0])
        invalid_calls = (
            ({"recipient": "Daniel", "message": "self"}, "self_recipient_forbidden"),
            ({"recipient": "all", "message": "broadcast"}, "invalid_recipient"),
            ({"recipient": "broadcast", "message": "broadcast"}, "invalid_recipient"),
            ({"recipient": "../Noah", "message": "path"}, "invalid_recipient"),
            ({"recipient": "rollout_001", "message": "id"}, "invalid_recipient"),
            (
                {"recipient": "Noah", "message": "spoof", "sender": "George"},
                "invalid_message_arguments",
            ),
            (
                {"recipient": "Noah", "message": "path", "path": "/tmp/messages"},
                "invalid_message_arguments",
            ),
            ({"recipient": "Noah", "message": ""}, "invalid_message"),
            ({"recipient": "Noah", "message": " \n\t"}, "invalid_message"),
            ({"recipient": "Noah", "message": "\x01x"}, "invalid_message_controls"),
            ({"recipient": "Noah", "message": "\u200b"}, "invalid_message_controls"),
            (
                {"recipient": "Noah", "message": "\ud800"},
                "invalid_message_encoding",
            ),
        )
        for index, (arguments, expected_code) in enumerate(invalid_calls):
            with self.subTest(arguments=arguments):
                result = deliver_private_message(
                    context=context,
                    args=arguments,
                    call_id=f"invalid-{index}",
                    progress_callback=lambda _fields: None,
                )
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], expected_code)
        self.assertEqual(list(configs[1].own_inbox.iterdir()), [])
        self.assertEqual(list(configs[2].own_inbox.iterdir()), [])

    def test_delivery_is_atomic_unique_and_progress_has_no_body(self) -> None:
        root = self._root()
        configs = self._configs(root, 2)
        progress: list[dict[str, object]] = []
        result = deliver_private_message(
            context=self._context(configs[0]),
            args={"recipient": "Noah", "message": BODY_SENTINEL},
            call_id="stable-call-1",
            progress_callback=progress.append,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(result["size"], len(BODY_SENTINEL.encode("utf-8")))
        self.assertNotIn(BODY_SENTINEL, json.dumps(result))
        self.assertNotIn("messages", json.dumps(result))
        self.assertNotIn(str(root), json.dumps(result))

        delivered = list(configs[1].own_inbox.iterdir())
        self.assertEqual([path.name for path in delivered], ["000001_Daniel.md"])
        self.assertEqual(
            delivered[0].read_text(encoding="utf-8"),
            f"# Message from Daniel\n\n{BODY_SENTINEL}\n",
        )
        self.assertEqual(delivered[0].stat().st_mode & 0o222, 0)
        self.assertEqual(
            set(progress[0]),
            {"sender", "recipient", "size", "sequence", "status"},
        )
        self.assertNotIn(BODY_SENTINEL, json.dumps(progress))

    def test_default_progress_record_is_strictly_metadata_only(self) -> None:
        root = self._root()
        configs = self._configs(root, 2)
        progress_log = root / "progress.jsonl"
        result = deliver_private_message(
            context=self._context(configs[0], progress_log),
            args={"recipient": "Noah", "message": BODY_SENTINEL},
            call_id="progress-call",
        )
        self.assertTrue(result["success"])
        record = json.loads(progress_log.read_text(encoding="utf-8"))
        self.assertEqual(
            set(record),
            {"sender", "recipient", "size", "sequence", "status"},
        )
        self.assertNotIn(BODY_SENTINEL, progress_log.read_text(encoding="utf-8"))

    def test_generic_codex_progress_does_not_duplicate_private_message_events(self) -> None:
        callbacks: list[tuple[str, dict[str, object]]] = []
        state = {
            "tool_call_count": 0,
            "spawn_child_tool_call_count": 0,
            "send_message_tool_call_count": 0,
            "resolution_phase": False,
        }
        events = io.StringIO()
        for event in (
            {
                "event": "tool_begin",
                "tool": "send_message",
                "call_id": "private-call-id",
                "arguments": {"redacted": True},
            },
            {
                "event": "tool_end",
                "tool": "send_message",
                "call_id": "private-call-id",
                "success": True,
            },
        ):
            _handle_runner_line(
                json.dumps(event),
                events_fh=events,
                progress_callback=lambda name, **fields: callbacks.append((name, fields)),
                state=state,
            )
        self.assertEqual(callbacks, [])
        self.assertEqual(state["send_message_tool_call_count"], 1)
        self.assertNotIn(BODY_SENTINEL, events.getvalue())

    def test_stable_call_id_is_idempotent_and_missing_id_may_duplicate(self) -> None:
        root = self._root()
        configs = self._configs(root, 2)
        context = self._context(configs[0])
        arguments = {"recipient": "Noah", "message": BODY_SENTINEL}
        first = deliver_private_message(
            context=context,
            args=arguments,
            call_id="same-call",
            progress_callback=lambda _fields: None,
        )
        duplicate = deliver_private_message(
            context=context,
            args=arguments,
            call_id="same-call",
            progress_callback=lambda _fields: None,
        )
        self.assertTrue(first["success"])
        self.assertTrue(duplicate["success"])
        self.assertEqual(first["sequence"], duplicate["sequence"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(len(list(configs[1].own_inbox.iterdir())), 1)

        conflict = deliver_private_message(
            context=context,
            args={"recipient": "Noah", "message": "different"},
            call_id="same-call",
            progress_callback=lambda _fields: None,
        )
        self.assertFalse(conflict["success"])
        self.assertEqual(conflict["error_code"], "call_id_conflict")

        no_id_one = deliver_private_message(
            context=context,
            args={"recipient": "Noah", "message": "without stable id"},
            call_id=None,
            progress_callback=lambda _fields: None,
        )
        no_id_two = deliver_private_message(
            context=context,
            args={"recipient": "Noah", "message": "without stable id"},
            call_id=None,
            progress_callback=lambda _fields: None,
        )
        self.assertTrue(no_id_one["success"] and no_id_two["success"])
        self.assertFalse(no_id_one["idempotent"])
        self.assertNotEqual(no_id_one["sequence"], no_id_two["sequence"])

    def test_delivery_accepts_messages_beyond_former_limits_without_loss(self) -> None:
        root = self._root()
        configs = self._configs(root, 2)
        former_byte_limit = 2_048
        former_sender_limit = 8
        former_batch_limit = 64

        def send(number: int):
            message = "x" * (former_byte_limit + 1) if number == 0 else f"message {number}"
            return deliver_private_message(
                context=self._context(configs[0]),
                args={"recipient": "Noah", "message": message},
                call_id=f"daniel-call-{number}",
                progress_callback=lambda _fields: None,
            )

        with ThreadPoolExecutor(max_workers=former_sender_limit + 2) as executor:
            results = list(executor.map(send, range(former_sender_limit + 2)))
        self.assertTrue(all(result["success"] for result in results))
        self.assertGreater(results[0]["size"], former_byte_limit)
        self.assertEqual(
            sorted(result["sequence"] for result in results),
            list(range(1, former_sender_limit + 3)),
        )
        self.assertEqual(
            len(list(configs[1].own_inbox.iterdir())),
            former_sender_limit + 2,
        )

        state_path = configs[0].state_path
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertNotIn("sender_counts", state)
        self.assertNotIn("total_count", state)
        state["next_sequence"] = former_batch_limit + 1
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
        beyond_former_batch = send(former_sender_limit + 2)
        self.assertTrue(beyond_former_batch["success"])
        self.assertEqual(beyond_former_batch["sequence"], former_batch_limit + 1)
        self.assertTrue(
            (configs[1].own_inbox / "000065_Daniel.md").is_file()
        )

    def test_central_callback_delivers_without_body_or_path_echo(self) -> None:
        root = self._root()
        configs = self._configs(root, 2)
        context_path = root / "continuation_context.json"
        context_path.write_text(
            json.dumps(self._context(configs[0])),
            encoding="utf-8",
        )
        payload = {
            "tool": "send_message",
            "call_id": "callback-call",
            "arguments": {"recipient": "Noah", "message": BODY_SENTINEL},
        }
        stdout = io.StringIO()
        previous_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            with redirect_stdout(stdout):
                run_child_tool_handler(context_path)
        finally:
            sys.stdin = previous_stdin
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["success"])
        self.assertNotIn(BODY_SENTINEL, stdout.getvalue())
        self.assertNotIn(str(root), stdout.getvalue())
        self.assertEqual(
            (configs[1].own_inbox / "000001_Daniel.md").read_text(encoding="utf-8"),
            f"# Message from Daniel\n\n{BODY_SENTINEL}\n",
        )

        namespaced = {
            **payload,
            "call_id": "namespaced-call",
            "namespace": "caller_selected",
        }
        stdout = io.StringIO()
        try:
            sys.stdin = io.StringIO(json.dumps(namespaced))
            with redirect_stdout(stdout):
                run_child_tool_handler(context_path)
        finally:
            sys.stdin = previous_stdin
        rejected = json.loads(stdout.getvalue())
        self.assertFalse(rejected["success"])
        self.assertEqual(
            rejected["error_code"],
            "unsupported_dynamic_tool_namespace",
        )
        self.assertEqual(len(list(configs[1].own_inbox.iterdir())), 1)

        stdout = io.StringIO()
        try:
            sys.stdin = io.StringIO(json.dumps(payload))
            with redirect_stdout(stdout):
                run_child_tool_handler(root / "missing-context.json")
        finally:
            sys.stdin = previous_stdin
        failed = json.loads(stdout.getvalue())
        self.assertFalse(failed["success"])
        self.assertEqual(failed["error_code"], "send_message_handler_failed")
        self.assertNotIn(BODY_SENTINEL, stdout.getvalue())
        self.assertNotIn(str(root), stdout.getvalue())

    def test_static_environment_projection_is_minimal_and_messages_are_not_persisted(self) -> None:
        root = self._root()
        contents = (
            Path(__file__).resolve().parents[1] / "seeds" / "bootstrap" / "README.md"
        ).read_text(encoding="utf-8")
        static_notice = (
            "`messages/` is this program's private, batch-local inbox. Other named "
            "programs can place files there through `send_message`, but cannot inspect "
            "the inbox. `runtime.md` lists the names. Messages disappear at the end "
            "of the round."
        )
        self.assertEqual(contents.count(static_notice), 1)
        self.assertNotIn("should send", contents.lower())

        runtime = _format_runtime_markdown(
            instance_uuid="fixture",
            has_problem_pool=False,
            human_name="Daniel",
            human_roster=ROLLOUT_HUMAN_NAMES,
        )
        self.assertIn("- own_name: Daniel", runtime)
        for index, name in enumerate(ROLLOUT_HUMAN_NAMES):
            self.assertIn(f"rollout_index={index} name={name}", runtime)
        self.assertNotIn("when to", runtime.lower())

        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "README.md").write_text("visible", encoding="utf-8")
        messages = workspace / "messages"
        messages.mkdir()
        (messages / "secret.md").write_text(BODY_SENTINEL, encoding="utf-8")
        output = persist_episode_outputs(
            workspace,
            root / "outputs",
            "fixture",
            exclude_names=("messages",),
        )
        self.assertTrue((output / "README.md").is_file())
        self.assertFalse((output / "messages").exists())

    def test_partial_v36_batches_fail_closed_but_completed_batches_are_immutable(self) -> None:
        args = Namespace(
            benchmark="open-ended",
            worker_backend="codex",
            num_rollouts=2,
        )
        old_record = {"task_index": 0, "rollout_index": 0, "task_rollout_count": 2}
        with self.assertRaisesRegex(SystemExit, "predates the v3.7"):
            _validate_private_inbox_partial_resume([old_record], args)

        current_record = {
            **old_record,
            "codex_capability_identity": PRIVATE_INBOX_CAPABILITY_IDENTITY,
        }
        _validate_private_inbox_partial_resume([current_record], args)
        _validate_private_inbox_partial_resume(
            [old_record, {**old_record, "rollout_index": 1}],
            args,
        )

        unchanged_args = Namespace(
            benchmark="arc-agi",
            worker_backend="codex",
            num_rollouts=2,
        )
        _validate_private_inbox_partial_resume([old_record], unchanged_args)

    def test_codex_request_exposes_private_tool_context_only_after_capability_probe(self) -> None:
        root = self._root()
        fake_runner = root / "fake-codex-runner"
        fake_runner.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            f"capability = {PRIVATE_INBOX_CAPABILITY_IDENTITY!r}\n"
            "if len(sys.argv) > 1 and sys.argv[1] == '--metalanguage-capabilities':\n"
            "    print(json.dumps({'protocol':'metalanguage-codex-runner','version':1,'capabilities':[capability]}))\n"
            "    raise SystemExit(0)\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'event':'thread_started','thread_id':'thread','session_id':'session'}), flush=True)\n"
            "print(json.dumps({'event':'turn_started','turn_id':'turn'}), flush=True)\n"
            "print(json.dumps({'event':'turn_complete','turn_id':'turn','final_text':'done'}), flush=True)\n",
            encoding="utf-8",
        )
        fake_runner.chmod(0o755)
        configs = self._configs(root / "rollouts", 2)
        paths = {
            name: root / name
            for name in ("control", "state", "codex", "seed", "archive", "shared")
        }
        for path in paths.values():
            path.mkdir(parents=True)
        (paths["codex"] / "sessions").mkdir()
        continuation = paths["control"] / "continuation_context.json"
        continuation.write_text("{}\n", encoding="utf-8")

        result = run_codex_rollout(
            runner_bin=fake_runner,
            model="fixture",
            workdir=configs[0].own_inbox.parent,
            control_dir=paths["control"],
            worker_state_dir=paths["state"],
            codex_home=paths["codex"],
            seed_output_dir=paths["seed"],
            archive_repo_dir=paths["archive"],
            archive_git_dir=None,
            shared_workspace_dir=paths["shared"],
            rollout_username="rollout_user_000",
            timeout_seconds=5,
            spawn_child_handler_context_path=continuation,
            persist_session=True,
            private_inbox=configs[0],
        )
        self.assertEqual(result["status"], "completed")
        request = json.loads(
            (paths["control"] / "codex_runner.request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            request["private_inbox"]["capability_identity"],
            PRIVATE_INBOX_CAPABILITY_IDENTITY,
        )
        self.assertEqual(request["private_inbox"]["sender"], "Daniel")
        self.assertEqual(set(request["private_inbox"]["recipient_inboxes"]), {"Noah"})
        self.assertNotIn("state_path", request["private_inbox"])
        self.assertNotIn("protected_read_paths", request["private_inbox"])
        self.assertEqual(
            request["private_evidence_protection"]["capability_identity"],
            PRIVATE_INBOX_CAPABILITY_IDENTITY,
        )
        self.assertIn(
            str(paths["codex"] / "sessions"),
            request["private_evidence_protection"]["read_denied_paths"],
        )
        self.assertIn("spawn_child_handler_command", request)

        with self.assertRaisesRegex(ValueError, "managed Codex sandbox"):
            run_codex_rollout(
                runner_bin=fake_runner,
                model="fixture",
                workdir=configs[0].own_inbox.parent,
                control_dir=root / "danger-control",
                worker_state_dir=paths["state"],
                codex_home=paths["codex"],
                seed_output_dir=paths["seed"],
                archive_repo_dir=paths["archive"],
                archive_git_dir=None,
                shared_workspace_dir=paths["shared"],
                rollout_username="rollout_user_000",
                timeout_seconds=5,
                sandbox_mode="danger-full-access",
                spawn_child_handler_context_path=continuation,
                private_inbox=configs[0],
            )

        rollout_path = root / "research-rollout.jsonl"
        rollout_path.write_text(
            json.dumps({"type": "session_meta", "payload": {"dynamic_tools": []}})
            + "\n",
            encoding="utf-8",
        )
        resolver_control = root / "resolver-control"
        resolver = run_codex_rollout(
            runner_bin=fake_runner,
            model="fixture",
            workdir=configs[0].own_inbox.parent,
            control_dir=resolver_control,
            worker_state_dir=paths["state"],
            codex_home=paths["codex"],
            seed_output_dir=paths["seed"],
            archive_repo_dir=paths["archive"],
            archive_git_dir=None,
            shared_workspace_dir=paths["shared"],
            rollout_username="rollout_user_000",
            timeout_seconds=5,
            resume_rollout_path=rollout_path,
            expected_thread_id="thread",
            expected_session_id="session",
            resolution_phase=True,
            protect_private_evidence=True,
        )
        self.assertEqual(resolver["status"], "completed")
        resolver_request = json.loads(
            (resolver_control / "codex_runner.request.json").read_text(encoding="utf-8")
        )
        self.assertTrue(resolver_request["resolution_phase"])
        self.assertNotIn("private_inbox", resolver_request)
        self.assertNotIn("spawn_child_handler_command", resolver_request)
        self.assertIn("private_evidence_protection", resolver_request)

        stale = root / "stale-runner"
        stale.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stale.chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, "does not report private-inbox"):
            run_codex_rollout(
                runner_bin=stale,
                model="fixture",
                workdir=configs[0].own_inbox.parent,
                control_dir=root / "stale-control",
                worker_state_dir=paths["state"],
                codex_home=paths["codex"],
                seed_output_dir=paths["seed"],
                archive_repo_dir=paths["archive"],
                archive_git_dir=None,
                shared_workspace_dir=paths["shared"],
                rollout_username="rollout_user_000",
                timeout_seconds=5,
                spawn_child_handler_context_path=continuation,
                private_inbox=configs[0],
            )

    def test_installed_codex_sandbox_enforces_narrow_inbox_read_denies(self) -> None:
        codex = shutil.which("codex")
        if codex is None:
            self.skipTest("Codex CLI is unavailable")
        root = self._root()
        codex_home = root / "codex-home"
        codex_home.mkdir()
        daniel = root / "Daniel"
        noah = root / "Noah"
        daniel_inbox = daniel / "messages"
        noah_inbox = noah / "messages"
        daniel_inbox.mkdir(parents=True)
        noah_inbox.mkdir(parents=True)
        noah_secret = noah_inbox / "000001_Daniel.md"
        noah_secret.write_text(BODY_SENTINEL, encoding="utf-8")
        noah_public = noah / "public.txt"
        noah_public.write_text("ordinary sibling data", encoding="utf-8")

        def sandbox_state(cwd: Path, own_inbox: Path, denied_inbox: Path):
            return {
                "permissionProfile": {
                    "type": "managed",
                    "file_system": {
                        "type": "restricted",
                        "entries": [
                            {
                                "path": {"type": "special", "value": {"kind": "root"}},
                                "access": "read",
                            },
                            {
                                "path": {"type": "path", "path": str(cwd)},
                                "access": "write",
                            },
                            {
                                "path": {"type": "path", "path": str(own_inbox)},
                                "access": "read",
                            },
                            {
                                "path": {"type": "path", "path": str(denied_inbox)},
                                "access": "deny",
                            },
                        ],
                    },
                    "network": "restricted",
                },
                "codexLinuxSandboxExe": None,
                "sandboxCwd": cwd.as_uri(),
                "useLegacyLandlock": False,
            }

        env = {**os.environ, "CODEX_HOME": str(codex_home)}
        sender = subprocess.run(
            [
                codex,
                "sandbox",
                "--sandbox-state-json",
                json.dumps(sandbox_state(daniel, daniel_inbox, noah_inbox)),
                "sh",
                "-c",
                'cat "$1"; cat "$2"',
                "sh",
                str(noah_public),
                str(noah_secret),
            ],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertNotEqual(sender.returncode, 0)
        self.assertIn("ordinary sibling data", sender.stdout)
        self.assertNotIn(BODY_SENTINEL, sender.stdout + sender.stderr)

        recipient = subprocess.run(
            [
                codex,
                "sandbox",
                "--sandbox-state-json",
                json.dumps(sandbox_state(noah, noah_inbox, daniel_inbox)),
                "cat",
                str(noah_secret),
            ],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(recipient.returncode, 0, recipient.stderr)
        self.assertEqual(recipient.stdout, BODY_SENTINEL)


if __name__ == "__main__":
    unittest.main()

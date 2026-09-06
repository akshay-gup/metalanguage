from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from main_loop import (
    ORDERED_ROLLOUT_MODE,
    PRIVATE_INBOX_CAPABILITY_IDENTITY,
    RUNTIME_ROLLOUT_IDENTITY_FILENAME,
    SHUFFLED_ROLLOUT_MODE,
    RolloutSlot,
    WorkerResult,
    _claim_runtime_rollout_identity,
    _claim_task_rollout_assignment,
    _fresh_rollout_permutation,
    _load_rollout_config,
    _load_task_rollout_assignment,
    _resolve_rollout_slots,
    _rollout_slot_argument,
    _run_main,
    _shuffled_rollout_metadata,
    _spawn_child_continuation,
    _validate_ordered_rollout_records,
    _validate_shuffled_rollout_records,
    parse_args,
)
from utils.opencode_runner import provider_environment_names
from utils.supergpqa_benchmark import SuperGpqaBenchmarkDriver, SuperGpqaConfig


class MixedRolloutBackendTests(unittest.TestCase):
    rollout_config_path = (
        Path(__file__).parents[1]
        / "configs/rollouts/gpt6-astra-openrouter-flash.json"
    )

    def test_rollout_slot_parsing_and_count_validation(self) -> None:
        self.assertEqual(
            _rollout_slot_argument("opencode=openai/gpt-5.1"),
            RolloutSlot("opencode", "openai/gpt-5.1"),
        )
        with self.assertRaisesRegex(Exception, "BACKEND=MODEL"):
            _rollout_slot_argument("codex")
        with self.assertRaisesRegex(Exception, "codex, opencode"):
            _rollout_slot_argument("openrouter=model")
        with self.assertRaisesRegex(Exception, "non-empty"):
            _rollout_slot_argument("codex=")

        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--num-rollouts",
                "2",
                "--rollout-slot",
                "codex=gpt-5.6-sol",
            ],
        ):
            args = parse_args()
        with self.assertRaisesRegex(SystemExit, "must equal --num-rollouts"):
            _resolve_rollout_slots(args)

    def test_homogeneous_flags_remain_the_default(self) -> None:
        args = Namespace(
            rollout_slot=[],
            num_rollouts=3,
            worker_backend="opencode",
            model="openai/gpt-5.1",
        )
        self.assertEqual(
            _resolve_rollout_slots(args),
            (RolloutSlot("opencode", "openai/gpt-5.1"),) * 3,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _claim_runtime_rollout_identity(
                root,
                _resolve_rollout_slots(args),
                explicitly_configured=False,
                runtime_was_empty=True,
            )
            self.assertFalse((root / RUNTIME_ROLLOUT_IDENTITY_FILENAME).exists())

        with patch("sys.argv", ["main_loop.py"]):
            defaults = parse_args()
        self.assertEqual(defaults.num_rollouts, 8)
        self.assertFalse(defaults._num_rollouts_explicit)

    def test_rollout_config_loads_in_order_and_infers_count(self) -> None:
        expected = (
            RolloutSlot("codex", "gpt-6-astra"),
            RolloutSlot("opencode", "openrouter/z-ai/glm-5.3-flash"),
            RolloutSlot(
                "opencode", "openrouter/deepseek/deepseek-v4-flash-0731"
            ),
            RolloutSlot("opencode", "openrouter/google/gemini-3.8-flash"),
            RolloutSlot(
                "opencode", "openrouter/meta/muse-spark-1.3-contributor"
            ),
            RolloutSlot("opencode", "openrouter/qwen/qwen3.8-flash"),
        )
        self.assertEqual(_load_rollout_config(self.rollout_config_path), expected)

        with patch(
            "sys.argv",
            ["main_loop.py", "--rollout-config", str(self.rollout_config_path)],
        ):
            args = parse_args()
        self.assertEqual(_resolve_rollout_slots(args), expected)
        self.assertEqual(args.num_rollouts, 6)
        self.assertFalse(args._num_rollouts_explicit)
        for slot in expected[1:]:
            self.assertEqual(
                provider_environment_names(slot.model), ("OPENROUTER_API_KEY",)
            )

    def test_rollout_config_explicit_count_must_match(self) -> None:
        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--rollout-config",
                str(self.rollout_config_path),
                "--num-rollouts",
                "6",
            ],
        ):
            matching = parse_args()
        self.assertEqual(len(_resolve_rollout_slots(matching)), 6)
        self.assertTrue(matching._num_rollouts_explicit)

        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--rollout-config",
                str(self.rollout_config_path),
                "--num-rollouts",
                "8",
            ],
        ):
            mismatching = parse_args()
        with self.assertRaisesRegex(SystemExit, "entries must equal --num-rollouts"):
            _resolve_rollout_slots(mismatching)

    def test_rollout_config_is_mutually_exclusive_with_slots(self) -> None:
        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--rollout-config",
                str(self.rollout_config_path),
                "--rollout-slot",
                "codex=gpt-6-astra",
            ],
        ), self.assertRaises(SystemExit):
            parse_args()

    def test_rollout_config_schema_is_strict(self) -> None:
        invalid_payloads = {
            "malformed": "{",
            "unknown_top_level": json.dumps(
                {
                    "format": "metalanguage-rollout-config",
                    "version": 1,
                    "rollouts": [{"backend": "codex", "model": "gpt"}],
                    "unexpected": True,
                }
            ),
            "unknown_entry_field": json.dumps(
                {
                    "format": "metalanguage-rollout-config",
                    "version": 1,
                    "rollouts": [
                        {"backend": "codex", "model": "gpt", "extra": None}
                    ],
                }
            ),
            "invalid_backend": json.dumps(
                {
                    "format": "metalanguage-rollout-config",
                    "version": 1,
                    "rollouts": [{"backend": "openrouter", "model": "model"}],
                }
            ),
            "duplicate_field": (
                '{"format":"metalanguage-rollout-config","version":1,'
                '"version":1,"rollouts":[]}'
            ),
            "duplicate_pool_entry": json.dumps(
                {
                    "format": "metalanguage-rollout-config",
                    "version": 1,
                    "rollouts": [
                        {"backend": "codex", "model": "gpt"},
                        {"backend": "codex", "model": "gpt"},
                    ],
                }
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            for name, payload in invalid_payloads.items():
                with self.subTest(name=name):
                    path = Path(temp) / f"{name}.json"
                    path.write_text(payload, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        _load_rollout_config(path)

    def test_rollout_pool_identity_is_path_independent(self) -> None:
        with patch(
            "sys.argv",
            ["main_loop.py", "--rollout-config", str(self.rollout_config_path)],
        ):
            config_args = parse_args()
        config_slots = _resolve_rollout_slots(config_args)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / "runtime"
            runtime.mkdir()
            copied_config = root / "renamed.json"
            copied_config.write_text(
                self.rollout_config_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            copied_slots = _load_rollout_config(copied_config)
            self.assertEqual(copied_slots, config_slots)
            _claim_runtime_rollout_identity(
                runtime,
                config_slots,
                explicitly_configured=True,
                runtime_was_empty=True,
                assignment_mode=SHUFFLED_ROLLOUT_MODE,
            )
            identity = json.loads(
                (runtime / RUNTIME_ROLLOUT_IDENTITY_FILENAME).read_text()
            )
            self.assertNotIn("rollout_config", identity)
            self.assertNotIn("rollout_slots", identity)
            self.assertEqual(
                identity["rollout_assignment_mode"], SHUFFLED_ROLLOUT_MODE
            )
            _claim_runtime_rollout_identity(
                runtime,
                copied_slots,
                explicitly_configured=True,
                runtime_was_empty=False,
                assignment_mode=SHUFFLED_ROLLOUT_MODE,
            )
            with self.assertRaisesRegex(SystemExit, "does not match"):
                _claim_runtime_rollout_identity(
                    runtime,
                    copied_slots,
                    explicitly_configured=True,
                    runtime_was_empty=False,
                    assignment_mode=ORDERED_ROLLOUT_MODE,
                )

    def test_task_rollout_assignments_are_persisted_permutations(self) -> None:
        rollout_pool = _load_rollout_config(self.rollout_config_path)

        def reverse(items: list[RolloutSlot]) -> None:
            items.reverse()

        def rotate(items: list[RolloutSlot]) -> None:
            items[:] = items[1:] + items[:1]

        with tempfile.TemporaryDirectory() as temp:
            assignment_root = Path(temp) / "assignments"
            task_zero = _claim_task_rollout_assignment(
                assignment_root,
                rollout_pool,
                task_index=0,
                shuffle=reverse,
            )
            recovered = _claim_task_rollout_assignment(
                assignment_root,
                rollout_pool,
                task_index=0,
                shuffle=lambda _: self.fail("recovery must not reshuffle"),
            )
            task_one = _claim_task_rollout_assignment(
                assignment_root,
                rollout_pool,
                task_index=1,
                shuffle=rotate,
            )

            self.assertEqual(recovered, task_zero)
            self.assertNotEqual(task_one, task_zero)
            for assignment in (task_zero, task_one):
                self.assertEqual(len(assignment), len(rollout_pool))
                self.assertEqual(len(set(assignment)), len(rollout_pool))
                self.assertEqual(set(assignment), set(rollout_pool))

            assignment_path = assignment_root / "000000.json"
            payload = json.loads(assignment_path.read_text())
            self.assertEqual(payload["task_index"], 0)
            self.assertEqual(
                payload["rollout_assignment_mode"], SHUFFLED_ROLLOUT_MODE
            )
            self.assertEqual(
                _load_task_rollout_assignment(
                    assignment_path, rollout_pool, task_index=0
                ),
                task_zero,
            )

    def test_invalid_task_assignment_fails_closed(self) -> None:
        rollout_pool = _load_rollout_config(self.rollout_config_path)
        with tempfile.TemporaryDirectory() as temp:
            assignment_root = Path(temp)
            rollout_slots = _claim_task_rollout_assignment(
                assignment_root,
                rollout_pool,
                task_index=3,
                shuffle=lambda _: None,
            )
            assignment_path = assignment_root / "000003.json"
            valid_payload = json.loads(assignment_path.read_text())
            invalid_payloads = {
                "repeated": (
                    {
                        **valid_payload,
                        "rollout_slots": [
                            valid_payload["rollout_slots"][0],
                            valid_payload["rollout_slots"][0],
                            *valid_payload["rollout_slots"][2:],
                        ],
                    },
                    "no-replacement permutation",
                ),
                "omitted": (
                    {
                        **valid_payload,
                        "rollout_slots": valid_payload["rollout_slots"][:-1],
                    },
                    "no-replacement permutation",
                ),
                "task_mismatch": (
                    {**valid_payload, "task_index": 4},
                    "identity mismatch",
                ),
                "pool_mismatch": (
                    {
                        **valid_payload,
                        "rollout_pool": list(reversed(valid_payload["rollout_pool"])),
                    },
                    "pool mismatch",
                ),
                "unknown_field": (
                    {**valid_payload, "unexpected": True},
                    "invalid schema",
                ),
            }
            for name, (payload, error) in invalid_payloads.items():
                with self.subTest(name=name):
                    path = assignment_root / f"invalid-{name}.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, error):
                        _load_task_rollout_assignment(
                            path, rollout_pool, task_index=3
                        )

            metadata = _shuffled_rollout_metadata(rollout_pool, rollout_slots)
            record = {
                "task_index": 3,
                "rollout_index": 0,
                "worker_backend": rollout_slots[0].worker_backend,
                "model": rollout_slots[0].model,
                "task_rollout_count": len(rollout_pool),
                "bootstrap_rollout_count": len(rollout_pool),
                **metadata,
            }
            _validate_shuffled_rollout_records(
                [record], rollout_pool, {3: rollout_slots}
            )
            record["task_rollout_count"] = len(rollout_pool) - 1
            with self.assertRaisesRegex(SystemExit, "does not match"):
                _validate_shuffled_rollout_records(
                    [record], rollout_pool, {3: rollout_slots}
                )

    def test_shuffle_injection_rejects_non_permutations(self) -> None:
        rollout_pool = _load_rollout_config(self.rollout_config_path)

        def duplicate(items: list[RolloutSlot]) -> None:
            items[1] = items[0]

        with self.assertRaisesRegex(ValueError, "valid permutation"):
            _fresh_rollout_permutation(rollout_pool, shuffle=duplicate)

    def test_ordered_identity_rejects_omitted_or_changed_resume(self) -> None:
        configured = (
            RolloutSlot("codex", "gpt-5.6-sol"),
            RolloutSlot("opencode", "openai/gpt-5.1"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _claim_runtime_rollout_identity(
                root,
                configured,
                explicitly_configured=True,
                runtime_was_empty=True,
            )
            payload = json.loads(
                (root / RUNTIME_ROLLOUT_IDENTITY_FILENAME).read_text()
            )
            self.assertEqual(payload["rollout_assignment_mode"], ORDERED_ROLLOUT_MODE)
            self.assertEqual(payload["rollout_slots"][1]["model"], "openai/gpt-5.1")
            with self.assertRaisesRegex(SystemExit, "repeat.*--rollout-slot"):
                _claim_runtime_rollout_identity(
                    root,
                    configured,
                    explicitly_configured=False,
                    runtime_was_empty=False,
                )
            with self.assertRaisesRegex(SystemExit, "does not match"):
                _claim_runtime_rollout_identity(
                    root,
                    tuple(reversed(configured)),
                    explicitly_configured=True,
                    runtime_was_empty=False,
                )
            with self.assertRaisesRegex(SystemExit, "persisted run record"):
                _validate_ordered_rollout_records(
                    [
                        {
                            "rollout_index": 1,
                            "worker_backend": "opencode",
                            "model": "openai/changed",
                            "rollout_assignment_mode": ORDERED_ROLLOUT_MODE,
                            "rollout_slots": [slot.to_metadata() for slot in configured],
                        }
                    ],
                    configured,
                    {
                        "rollout_assignment_mode": ORDERED_ROLLOUT_MODE,
                        "rollout_slots": [slot.to_metadata() for slot in configured],
                    },
                )

    def test_codex_and_opencode_share_managed_supergpqa_batch_shape(self) -> None:
        rows = [
            {
                "id": "fixture",
                "question": "Question?",
                "answer": "B",
                "options": ["A", "B"],
            }
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = SuperGpqaBenchmarkDriver(
                SuperGpqaConfig(
                    dataset_name="fixture",
                    split="test",
                    config_name=None,
                    seed=17,
                    question_key=None,
                    answer_key=None,
                    id_key=None,
                    difficulty_filter=None,
                    start_task_index=0,
                    problem_pool_size=None,
                    queue_path=root / "queue.json",
                    task_store_dir=root / "private",
                    dataset_cache_dir=root / "cache",
                    backend="codex",
                ),
                rows=rows,
            )
            batch = driver.prepare_batch(0, root / "shared")
            context = {
                "continuation_context_path": str(root / "context.json"),
                "benchmark_events_path": str(root / "events.jsonl"),
            }
            codex = driver.prepare_rollout(batch, backend="codex", context=context)
            opencode = driver.prepare_rollout(
                batch, backend="opencode", context=context
            )
            self.assertEqual(set(codex.mcp_servers), {"supergpqa"})
            self.assertEqual(set(opencode.mcp_servers), {"supergpqa"})

    def test_mixed_dispatch_provider_routing_resume_and_record_metadata(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=documents) as temp:
            root = Path(temp)
            runtime = root / "runtime"
            task = root / "task.md"
            task.write_text("# Mixed backend fixture\n", encoding="utf-8")
            executables = {
                name: root / name for name in ("codex-runner", "opencode", "bun", "bwrap")
            }
            for path in executables.values():
                path.write_text("fixture\n", encoding="utf-8")
                path.chmod(0o755)

            argv = [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                str(task),
                "--runtime-root",
                str(runtime),
                "--worker-backend",
                "openrouter",
                "--model",
                "ignored/homogeneous-model",
                "--num-rollouts",
                "3",
                "--rollout-slot",
                "codex=gpt-5.6-sol",
                "--rollout-slot",
                "opencode=openai/gpt-5.1",
                "--rollout-slot",
                "opencode=anthropic/claude-sonnet-4-5",
                "--step",
            ]
            codex_calls: list[dict[str, object]] = []
            opencode_calls: list[dict[str, object]] = []

            def codex_worker(**kwargs: object) -> WorkerResult:
                codex_calls.append(kwargs)
                return WorkerResult(
                    "codex fixture", "completed", "final_message", metadata={"turn_count": 1}
                )

            def opencode_worker(**kwargs: object) -> WorkerResult:
                opencode_calls.append(kwargs)
                return WorkerResult(
                    "opencode fixture", "completed", "final_message", metadata={"turn_count": 1}
                )

            def version(path: Path) -> str:
                return {
                    "opencode": "1.18.29",
                    "bun": "1.3.14",
                    "bwrap": "bubblewrap 0.11.0",
                }[path.name]

            def configure_runtime(runtime_root: Path, *, include_huggingface: bool = True) -> Path:
                cache = runtime_root / "cache" / "fixture"
                cache.mkdir(parents=True, exist_ok=True)
                return cache

            patches = (
                patch("main_loop.load_dotenv"),
                patch("main_loop.resolve_codex_runner_bin", return_value=executables["codex-runner"]),
                patch("main_loop.resolve_opencode_worker_script", return_value=Path(__file__).parents[1] / "workers/opencode/worker.ts"),
                patch("main_loop.resolve_opencode_bin", return_value=executables["opencode"]),
                patch("main_loop.resolve_bun_bin", return_value=executables["bun"]),
                patch("main_loop.resolve_bubblewrap_bin", return_value=executables["bwrap"]),
                patch("main_loop.validate_opencode_host_primitives"),
                patch("main_loop.executable_version", side_effect=version),
                patch("main_loop.file_sha256", side_effect=lambda path: f"sha:{Path(path).name}"),
                patch("main_loop.opencode_worker_fingerprint", return_value="worker-sha"),
                patch("main_loop.opencode_python_fingerprint", return_value="python-sha"),
                patch("main_loop._configure_runtime_environment", side_effect=configure_runtime),
                patch("main_loop.run_codex_worker", side_effect=codex_worker),
                patch("main_loop.run_opencode_worker", side_effect=opencode_worker),
            )
            with patch.dict(
                "os.environ",
                {
                    "HOME": str(Path.home()),
                    "OPENAI_API_KEY": "openai-fixture-secret",
                    "ANTHROPIC_API_KEY": "anthropic-fixture-secret",
                },
                clear=True,
            ), patch("sys.argv", argv):
                for active_patch in patches:
                    active_patch.start()
                try:
                    _run_main([])
                    _run_main([])
                finally:
                    for active_patch in reversed(patches):
                        active_patch.stop()

            self.assertEqual([call["model"] for call in codex_calls], ["gpt-5.6-sol"] * 2)
            self.assertEqual(
                Counter(call["model"] for call in opencode_calls),
                Counter(
                    {
                        "openai/gpt-5.1": 2,
                        "anthropic/claude-sonnet-4-5": 2,
                    }
                ),
            )
            openai_call = next(
                call for call in opencode_calls if call["model"] == "openai/gpt-5.1"
            )
            anthropic_call = next(
                call
                for call in opencode_calls
                if call["model"] == "anthropic/claude-sonnet-4-5"
            )
            self.assertIn("OPENAI_API_KEY", openai_call["provider_env_names"])
            self.assertNotIn("ANTHROPIC_API_KEY", openai_call["provider_env_names"])
            self.assertEqual(
                anthropic_call["provider_env_names"], ("ANTHROPIC_API_KEY",)
            )
            self.assertEqual(
                set(openai_call["provider_environment"]), {"OPENAI_API_KEY"}
            )
            self.assertEqual(
                set(anthropic_call["provider_environment"]),
                {"ANTHROPIC_API_KEY"},
            )
            self.assertIsNone(openai_call["auth_file"])
            self.assertIsNotNone(codex_calls[0]["private_inbox"])
            self.assertIsNotNone(openai_call["private_inbox"])
            continuation = json.loads(
                Path(str(openai_call["continuation_context_path"])).read_text()
            )
            self.assertEqual(
                continuation["rollout_assignment_mode"], ORDERED_ROLLOUT_MODE
            )
            self.assertEqual(continuation["rollout_slots"][0]["worker_backend"], "codex")

            records = [
                json.loads(line)
                for line in (runtime / "logs/runs.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(records), 6)
            expected = {
                0: ("codex", "gpt-5.6-sol"),
                1: ("opencode", "openai/gpt-5.1"),
                2: ("opencode", "anthropic/claude-sonnet-4-5"),
            }
            for record in records:
                backend, model = expected[record["rollout_index"]]
                self.assertEqual((record["worker_backend"], record["model"]), (backend, model))
                self.assertEqual(record["rollout_assignment_mode"], ORDERED_ROLLOUT_MODE)
                self.assertEqual(len(record["rollout_slots"]), 3)
                capability_key = (
                    "codex_capability_identity"
                    if backend == "codex"
                    else "opencode_capability_identity"
                )
                self.assertEqual(
                    record[capability_key], PRIVATE_INBOX_CAPABILITY_IDENTITY
                )
            task_one = [record for record in records if record["task_index"] == 1]
            self.assertEqual(
                [(record["worker_backend"], record["model"]) for record in task_one],
                [expected[index] for index in range(3)],
            )
            self.assertNotEqual(
                task_one[1]["opencode_provider_env_sha256"],
                task_one[2]["opencode_provider_env_sha256"],
            )

            progress = [
                json.loads(line)
                for line in (runtime / "logs/progress.jsonl").read_text().splitlines()
            ]
            started = [item for item in progress if item["event"] == "rollout_started"]
            self.assertEqual(len(started), 6)
            self.assertEqual(
                {
                    (item["task_index"], item["rollout_index"]): (
                        item["worker_backend"],
                        item["model"],
                    )
                    for item in started
                },
                {
                    (task_index, rollout_index): expected[rollout_index]
                    for task_index in (0, 1)
                    for rollout_index in range(3)
                },
            )

    def test_shuffled_pool_dispatches_cross_model_child_continuations(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=documents) as temp:
            root = Path(temp)
            runtime = root / "runtime"
            task = root / "task.md"
            task.write_text("# Shuffled pool fixture\n", encoding="utf-8")
            config = root / "pool.json"
            config.write_text(
                json.dumps(
                    {
                        "format": "metalanguage-rollout-config",
                        "version": 1,
                        "rollouts": [
                            {"backend": "codex", "model": "gpt-fixture"},
                            {
                                "backend": "opencode",
                                "model": "openrouter/provider-fixture/model",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rollout_pool = _load_rollout_config(config)
            task_assignments = [rollout_pool, tuple(reversed(rollout_pool))]
            executables = {
                name: root / name
                for name in ("codex-runner", "opencode", "bun", "bwrap")
            }
            for path in executables.values():
                path.write_text("fixture\n", encoding="utf-8")
                path.chmod(0o755)

            argv = [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                str(task),
                "--runtime-root",
                str(runtime),
                "--rollout-config",
                str(config),
                "--step",
            ]
            calls: list[dict[str, object]] = []

            def worker(worker_backend: str, **kwargs: object) -> WorkerResult:
                context_path = Path(str(kwargs["continuation_context_path"]))
                context = json.loads(context_path.read_text())
                calls.append(
                    {
                        "worker_backend": worker_backend,
                        "task_index": context["task_index"],
                        "rollout_index": context["rollout_index"],
                        "model": kwargs["model"],
                        "initial_user_text": kwargs["initial_user_text"],
                        "provider_env_names": kwargs.get("provider_env_names"),
                        "rollout_assignment_mode": context.get(
                            "rollout_assignment_mode"
                        ),
                        "rollout_pool": context.get("rollout_pool"),
                        "rollout_slots": context.get("rollout_slots"),
                    }
                )
                if context["task_index"] == 0:
                    handoff = Path(str(kwargs["workdir"])) / "handoff"
                    handoff.mkdir()
                    (handoff / "README.md").write_text(
                        f"lineage {context['rollout_index']} from {kwargs['model']}\n",
                        encoding="utf-8",
                    )
                    spawned = _spawn_child_continuation(
                        context=context,
                        args={
                            "prompt": (
                                f"continue lineage {context['rollout_index']} "
                                f"from {kwargs['model']}"
                            ),
                            "workspace_dir": "handoff",
                        },
                    )
                    if not spawned["success"]:
                        raise RuntimeError(str(spawned))
                return WorkerResult(
                    f"{worker_backend} fixture",
                    "completed",
                    "final_message",
                    metadata={"turn_count": 1},
                )

            def version(path: Path) -> str:
                return {
                    "opencode": "1.18.29",
                    "bun": "1.3.14",
                    "bwrap": "bubblewrap 0.11.0",
                }[path.name]

            def configure_runtime(
                runtime_root: Path, *, include_huggingface: bool = True
            ) -> Path:
                cache = runtime_root / "cache" / "fixture"
                cache.mkdir(parents=True, exist_ok=True)
                return cache

            patches = (
                patch("main_loop.load_dotenv"),
                patch(
                    "main_loop.resolve_codex_runner_bin",
                    return_value=executables["codex-runner"],
                ),
                patch(
                    "main_loop.resolve_opencode_worker_script",
                    return_value=Path(__file__).parents[1]
                    / "workers/opencode/worker.ts",
                ),
                patch(
                    "main_loop.resolve_opencode_bin",
                    return_value=executables["opencode"],
                ),
                patch(
                    "main_loop.resolve_bun_bin", return_value=executables["bun"]
                ),
                patch(
                    "main_loop.resolve_bubblewrap_bin",
                    return_value=executables["bwrap"],
                ),
                patch("main_loop.validate_opencode_host_primitives"),
                patch("main_loop.executable_version", side_effect=version),
                patch(
                    "main_loop.file_sha256",
                    side_effect=lambda path: f"sha:{Path(path).name}",
                ),
                patch(
                    "main_loop.opencode_worker_fingerprint",
                    return_value="worker-sha",
                ),
                patch(
                    "main_loop.opencode_python_fingerprint",
                    return_value="python-sha",
                ),
                patch(
                    "main_loop._configure_runtime_environment",
                    side_effect=configure_runtime,
                ),
                patch(
                    "main_loop._fresh_rollout_permutation",
                    side_effect=task_assignments,
                ),
                patch(
                    "main_loop.run_codex_worker",
                    side_effect=lambda **kwargs: worker("codex", **kwargs),
                ),
                patch(
                    "main_loop.run_opencode_worker",
                    side_effect=lambda **kwargs: worker("opencode", **kwargs),
                ),
            )
            with patch.dict(
                "os.environ",
                {
                    "HOME": str(Path.home()),
                    "OPENROUTER_API_KEY": "openrouter-fixture-secret",
                },
                clear=True,
            ), patch("sys.argv", argv):
                for active_patch in patches:
                    active_patch.start()
                try:
                    _run_main([])
                    _run_main([])
                finally:
                    for active_patch in reversed(patches):
                        active_patch.stop()

            self.assertEqual(len(calls), 4)
            by_task_and_lineage = {
                (int(call["task_index"]), int(call["rollout_index"])): call
                for call in calls
            }
            self.assertEqual(
                by_task_and_lineage[(0, 0)]["model"], "gpt-fixture"
            )
            self.assertEqual(
                by_task_and_lineage[(1, 0)]["model"],
                "openrouter/provider-fixture/model",
            )
            self.assertEqual(
                by_task_and_lineage[(1, 0)]["initial_user_text"],
                "continue lineage 0 from gpt-fixture",
            )
            self.assertEqual(
                by_task_and_lineage[(1, 0)]["provider_env_names"],
                ("OPENROUTER_API_KEY",),
            )
            self.assertEqual(
                by_task_and_lineage[(1, 0)]["rollout_assignment_mode"],
                SHUFFLED_ROLLOUT_MODE,
            )
            self.assertEqual(len(by_task_and_lineage[(1, 0)]["rollout_pool"]), 2)
            self.assertEqual(len(by_task_and_lineage[(1, 0)]["rollout_slots"]), 2)

            assignment_paths = sorted(
                (runtime / "logs/rollout_assignments").glob("*.json")
            )
            self.assertEqual(
                [path.name for path in assignment_paths],
                ["000000.json", "000001.json"],
            )
            records = [
                json.loads(line)
                for line in (runtime / "logs/runs.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(records), 4)
            for record in records:
                assignment = task_assignments[record["task_index"]]
                expected_slot = assignment[record["rollout_index"]]
                self.assertEqual(
                    (record["worker_backend"], record["model"]),
                    (expected_slot.worker_backend, expected_slot.model),
                )
                self.assertEqual(
                    record["rollout_assignment_mode"], SHUFFLED_ROLLOUT_MODE
                )
                self.assertEqual(len(record["rollout_pool"]), 2)
                self.assertEqual(len(record["rollout_slots"]), 2)

            progress = [
                json.loads(line)
                for line in (runtime / "logs/progress.jsonl").read_text().splitlines()
            ]
            ready = [
                item
                for item in progress
                if item["event"] == "task_rollout_assignment_ready"
            ]
            self.assertEqual(len(ready), 2)
            self.assertTrue(
                all(item["rollout_assignment_mode"] == SHUFFLED_ROLLOUT_MODE for item in ready)
            )


if __name__ == "__main__":
    unittest.main()

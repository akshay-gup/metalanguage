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
    RolloutSlot,
    WorkerResult,
    _claim_runtime_rollout_identity,
    _resolve_rollout_slots,
    _rollout_slot_argument,
    _run_main,
    _validate_ordered_rollout_records,
    parse_args,
)
from utils.supergpqa_benchmark import SuperGpqaBenchmarkDriver, SuperGpqaConfig


class MixedRolloutBackendTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

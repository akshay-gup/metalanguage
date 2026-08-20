from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from main_loop import (
    _create_benchmark_driver,
    _format_runtime_markdown,
    _runtime_benchmark,
    parse_args,
)
from utils.open_ended_benchmark import (
    OpenEndedBenchmarkDriver,
    OpenEndedConfig,
    resolve_open_ended_task,
)


class OpenEndedBenchmarkTests(unittest.TestCase):
    def test_cli_accepts_open_ended_task_file(self) -> None:
        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                "task.md",
            ],
        ):
            args = parse_args()
        self.assertEqual(args.benchmark, "open-ended")
        self.assertEqual(args.task_file, "task.md")

    def test_exact_task_materialization_has_no_pool_tools_or_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "human-task.md"
            task_bytes = "# Human task\r\n\r\nDo the open-ended work. 🛠️\r\n".encode()
            source.write_bytes(task_bytes)
            state_dir = root / "runtime/logs/open_ended_task"
            task = resolve_open_ended_task(state_dir, source)
            self.assertFalse(state_dir.exists())
            driver = OpenEndedBenchmarkDriver(
                OpenEndedConfig(task=task, state_dir=state_dir)
            )

            shared = root / "shared"
            batch = driver.prepare_batch(4, shared)
            self.assertEqual(batch.benchmark, "open-ended")
            self.assertEqual(batch.item_count, 0)
            self.assertFalse(batch.metadata["has_problem_pool"])
            self.assertEqual(batch.metadata["evaluation"], "unconfigured")
            self.assertEqual((shared / "BENCHMARK.md").read_bytes(), task_bytes)
            self.assertEqual((state_dir / "task.md").read_bytes(), task_bytes)
            self.assertFalse((shared / "problem_pool.json").exists())
            self.assertFalse((shared / "problem_pool.md").exists())

            metadata = json.loads((state_dir / "task.json").read_text())
            self.assertEqual(metadata["sha256"], task.sha256)
            self.assertEqual(metadata["evaluation"], "unconfigured")
            rollout = driver.prepare_rollout(
                batch,
                backend="codex",
                context={"instance_uuid": "fixture"},
            )
            self.assertEqual(rollout.mcp_servers, {})
            self.assertEqual(rollout.sensitive_mcp_tools, ())
            self.assertEqual(rollout.model_metadata["tools"], [])
            self.assertEqual(rollout.context["evaluation"], "unconfigured")
            self.assertIsNone(
                driver.collect_outcome(
                    batch,
                    instance_uuid="fixture",
                    context=rollout.context,
                )
            )
            self.assertEqual(driver.finalize_batch(batch, []), {})
            driver.close()

    def test_runtime_copy_supports_resume_and_rejects_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "task.md"
            source.write_text("# Stable task\n", encoding="utf-8")
            state_dir = root / "runtime/logs/open_ended_task"
            initial = resolve_open_ended_task(state_dir, source)
            driver = OpenEndedBenchmarkDriver(
                OpenEndedConfig(task=initial, state_dir=state_dir)
            )
            driver.prepare_batch(0, root / "shared")
            driver.close()

            source.unlink()
            resumed = resolve_open_ended_task(state_dir, None)
            self.assertEqual(resumed.content, b"# Stable task\n")
            self.assertEqual(resumed.sha256, initial.sha256)

            replacement = root / "replacement.md"
            replacement.write_text("# Different task\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                resolve_open_ended_task(state_dir, replacement)

    def test_new_runtime_requires_a_nonblank_utf8_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "required"):
                resolve_open_ended_task(root / "state", None)

            blank = root / "blank.md"
            blank.write_text("  \n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not be blank"):
                resolve_open_ended_task(root / "state", blank)

            invalid = root / "invalid.md"
            invalid.write_bytes(b"\xff")
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                resolve_open_ended_task(root / "state", invalid)

    def test_main_loop_driver_and_runtime_projection_are_explicitly_unscored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "task.md"
            source.write_text("# Task\n", encoding="utf-8")
            task = resolve_open_ended_task(root / "state", source)
            driver = _create_benchmark_driver(
                Namespace(benchmark="open-ended"),
                arc_benchmark_state_path=root / "arc.json",
                problem_queue_path=root / "queue.json",
                task_store_dir=root / "tasks",
                dataset_cache_dir=root / "cache",
                existing_records=[],
                open_ended_task=task,
                open_ended_state_dir=root / "state",
            )
            self.assertIsInstance(driver, OpenEndedBenchmarkDriver)
            driver.close()

            runtime_text = _format_runtime_markdown(
                instance_uuid="fixture",
                has_problem_pool=False,
            )
            self.assertIn("evaluation: unconfigured", runtime_text)
            self.assertIn("no evaluator, score, reward, solved status, or ranking", runtime_text)
            self.assertNotIn("problem_pool", runtime_text)
            self.assertNotIn("Benchmark Pool Semantics", runtime_text)
            bootstrap = (
                Path(__file__).resolve().parents[1] / "seeds/bootstrap/README.md"
            ).read_text(encoding="utf-8")
            bootstrap_words = " ".join(bootstrap.split())
            self.assertIn("current human-authored task", bootstrap)
            self.assertIn("explicitly unevaluated", bootstrap_words)
            self.assertIn("an unevaluated profile can provide none", bootstrap)

            identity_root = root / "identity"
            identity_root.mkdir()
            (identity_root / "runtime_benchmark.json").write_text(
                json.dumps(
                    {
                        "format": "metalanguage-runtime-benchmark",
                        "version": 1,
                        "benchmark": "open-ended",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(_runtime_benchmark(identity_root), "open-ended")


if __name__ == "__main__":
    unittest.main()

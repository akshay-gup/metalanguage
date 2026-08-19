from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import main_loop
from main_loop import (
    _record_spawned_child,
    _format_runtime_markdown,
    _load_spawned_child_slots,
    _parse_spawn_child_arguments,
    _refill_parent_pool_with_bootstrap_slots,
    _spawn_child_continuation,
    _resolve_spawn_workspace_dir,
    _spawn_item_ref,
    create_archive_worktree,
    discard_archive_worktree,
    ensure_local_world_repo,
)
from utils.benchmark_driver import (
    BenchmarkDriver,
    BenchmarkItemRef,
    BenchmarkOutcome,
    PreparedBatch,
    RolloutBenchmark,
    active_benchmark_item,
)
from utils.benchmark_events import append_benchmark_event
from utils.supergpqa_benchmark import SuperGpqaBenchmarkDriver, SuperGpqaConfig
from utils.supergpqa_submit import submit_solution


ROWS = [
    {"id": f"task-{index}", "question": f"Question {index}?", "answer": "B", "options": ["A", "B", "C"]}
    for index in range(6)
]


class BenchmarkDriverTests(unittest.TestCase):
    def make_driver(self, root: Path, *, cap: int | None = 3, backend: str = "codex") -> SuperGpqaBenchmarkDriver:
        return SuperGpqaBenchmarkDriver(
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
                problem_pool_size=cap,
                queue_path=root / "queue.json",
                task_store_dir=root / "private",
                dataset_cache_dir=root / "cache",
                backend=backend,
            ),
            rows=ROWS,
        )

    def test_spawn_child_requires_non_blank_root_readme(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = {"workdir": str(root)}
            _, _, missing_workspace_error = _parse_spawn_child_arguments(
                {"prompt": "child"}
            )
            self.assertIn("workspace_dir", missing_workspace_error or "")

            workspace = root / "workspace"
            workspace.mkdir()
            resolved, missing_readme_error = _resolve_spawn_workspace_dir(
                context, "workspace"
            )
            self.assertIsNone(resolved)
            self.assertIn("README.md", missing_readme_error or "")

            (workspace / "README.md").write_text("   \n")
            resolved, blank_readme_error = _resolve_spawn_workspace_dir(
                context, "workspace"
            )
            self.assertIsNone(resolved)
            self.assertIn("non-blank", blank_readme_error or "")

            (workspace / "README.md").write_bytes(b"\xff")
            resolved, invalid_utf8_error = _resolve_spawn_workspace_dir(
                context, "workspace"
            )
            self.assertIsNone(resolved)
            self.assertIn("UTF-8", invalid_utf8_error or "")

            outside_readme = root / "outside-README.md"
            outside_readme.write_text("# Outside\n")
            (workspace / "README.md").unlink()
            (workspace / "README.md").symlink_to(outside_readme)
            resolved, symlink_readme_error = _resolve_spawn_workspace_dir(
                context, "workspace"
            )
            self.assertIsNone(resolved)
            self.assertIn("regular README.md", symlink_readme_error or "")

            (workspace / "README.md").unlink()
            (workspace / "README.md").write_text("# Child\n")
            resolved, error = _resolve_spawn_workspace_dir(context, "workspace")
            self.assertEqual(resolved, workspace)
            self.assertIsNone(error)

    def test_spawn_child_is_reserved_per_rollout_and_failures_do_not_consume_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            slots_path = root / "slots.json"
            slots_dir = root / "slots"

            def context(rollout_index: int) -> dict[str, object]:
                return {
                    "workdir": str(root),
                    "spawn_slots_path": str(slots_path),
                    "spawn_slots_dir": str(slots_dir),
                    "population_size": 2,
                    "task_id": "task",
                    "task_index": 0,
                    "rollout_index": rollout_index,
                    "rollout_username": f"rollout-{rollout_index}",
                    "instance_uuid": f"parent-{rollout_index}",
                }

            first_workspace = root / "first-child"
            first_workspace.mkdir()
            invalid = _spawn_child_continuation(
                context=context(0),
                args={"prompt": "first", "workspace_dir": "first-child"},
                progress_callback=lambda *_args, **_kwargs: None,
            )
            self.assertFalse(invalid["child_spawned"])
            self.assertTrue(invalid["retryable"])

            (first_workspace / "README.md").write_text("# First child\n")
            with patch("main_loop.copy_seed_workspace", side_effect=RuntimeError("copy failed")):
                copy_failed = _spawn_child_continuation(
                    context=context(0),
                    args={"prompt": "first", "workspace_dir": "first-child"},
                    progress_callback=lambda *_args, **_kwargs: None,
                )
            self.assertFalse(copy_failed["child_spawned"])
            self.assertTrue(copy_failed["retryable"])
            self.assertFalse(slots_path.exists())

            spawned = _spawn_child_continuation(
                context=context(0),
                args={"prompt": "first", "workspace_dir": "first-child"},
                progress_callback=lambda *_args, **_kwargs: None,
            )
            self.assertTrue(spawned["child_spawned"])
            self.assertTrue(spawned["parent_continues"])
            self.assertEqual(spawned["slot_index"], 0)
            self.assertIn("parent rollout continues", spawned["message"])

            duplicate = _spawn_child_continuation(
                context=context(0),
                args={},
                progress_callback=lambda *_args, **_kwargs: None,
            )
            self.assertFalse(duplicate["child_spawned"])
            self.assertFalse(duplicate["retryable"])
            self.assertTrue(duplicate["parent_continues"])
            self.assertEqual(duplicate["error_code"], "child_already_spawned")

            second_workspace = root / "second-child"
            second_workspace.mkdir()
            (second_workspace / "README.md").write_text("# Second child\n")
            second = _spawn_child_continuation(
                context=context(1),
                args={"prompt": "second", "workspace_dir": "second-child"},
                progress_callback=lambda *_args, **_kwargs: None,
            )
            self.assertTrue(second["child_spawned"])
            self.assertEqual(second["slot_index"], 1)
            state = json.loads(slots_path.read_text())
            self.assertEqual(
                [slot["source_rollout_index"] for slot in state["slots"]],
                [0, 1],
            )
            spawned_children = _load_spawned_child_slots(slots_path)
            parent_pool, bootstrap_count = _refill_parent_pool_with_bootstrap_slots(
                spawned_children,
                target_count=3,
            )
            self.assertEqual(bootstrap_count, 1)
            self.assertEqual(
                [slot["source_rollout_index"] for slot in parent_pool[:2]],
                [0, 1],
            )
            self.assertTrue(parent_pool[2]["bootstrap_reinitialized"])

    def test_bootstrap_refill_preserves_sparse_rollout_slot_indices(self) -> None:
        spawned_children = [
            {
                "source_rollout_index": slot_index,
                "slot_index": slot_index,
                "child_instance_uuid": f"child-{slot_index}",
            }
            for slot_index in (0, 2, 3, 4, 5, 6, 7)
        ]

        parent_pool, bootstrap_count = _refill_parent_pool_with_bootstrap_slots(
            spawned_children,
            target_count=8,
        )

        self.assertEqual(bootstrap_count, 1)
        self.assertEqual([slot["slot_index"] for slot in parent_pool], list(range(8)))
        self.assertEqual(
            [slot.get("source_rollout_index") for slot in parent_pool],
            [0, None, 2, 3, 4, 5, 6, 7],
        )
        self.assertTrue(parent_pool[1]["bootstrap_reinitialized"])
        self.assertIs(parent_pool[7], spawned_children[-1])
        self.assertEqual(parent_pool[7]["child_instance_uuid"], "child-7")

    def test_protocol_shape_deterministic_pool_resume_and_backend_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = self.make_driver(root)
            self.assertIsInstance(driver, BenchmarkDriver)
            first = driver.prepare_batch(4, root / "shared")
            first_ids = [record.problem_uid for record in first.private]
            second = self.make_driver(root).prepare_batch(4, root / "shared2")
            self.assertEqual(first_ids, [record.problem_uid for record in second.private])
            self.assertEqual(len(first_ids), 3)
            queue = json.loads((root / "queue.json").read_text())
            self.assertEqual(queue["next_task_index"], len(ROWS))

            base = {
                "continuation_context_path": str(root / "private-context.json"),
                "benchmark_events_path": str(root / "benchmark-events.jsonl"),
            }
            codex = driver.prepare_rollout(first, backend="codex", context=base)
            self.assertIsInstance(codex, RolloutBenchmark)
            self.assertEqual(set(codex.mcp_servers), {"supergpqa"})
            codex_readme = codex.model_metadata["benchmark_readme"]
            self.assertIn(
                "mcp__supergpqa__submit_solution",
                codex_readme,
            )
            self.assertEqual(
                codex_readme.strip(),
                (root / "shared" / "BENCHMARK.md").read_text().strip(),
            )
            self.assertNotIn("answer", json.dumps(codex.context["problem_pool_records"]))
            self.assertIn("mcp__supergpqa__submit_solution", (root / "shared" / "problem_pool.md").read_text())
            open_root = root / "openrouter"
            open_driver = self.make_driver(open_root, backend="openrouter")
            open_batch = open_driver.prepare_batch(4, open_root / "shared")
            openrouter = open_driver.prepare_rollout(open_batch, backend="openrouter", context=base)
            self.assertFalse(openrouter.mcp_servers)
            openrouter_readme = openrouter.model_metadata["benchmark_readme"]
            self.assertIn(
                "submit_solution(uuid=", openrouter_readme
            )
            self.assertEqual(
                openrouter_readme.strip(),
                (open_root / "shared" / "BENCHMARK.md").read_text().strip(),
            )
            self.assertIn("submit_solution(uuid=", (open_root / "shared" / "problem_pool.md").read_text())
            self.assertNotIn("mcp__", (open_root / "shared" / "problem_pool.md").read_text())
            stable_readme = (
                Path(__file__).resolve().parents[1] / "seeds/bootstrap/README.md"
            ).read_text()
            stable_readme_words = " ".join(stable_readme.split())
            self.assertNotIn("SuperGPQA", stable_readme)
            self.assertNotIn("submit_solution", stable_readme)
            self.assertIn("Benchmark-specific tools", stable_readme)
            self.assertIn("spawn_child", stable_readme)
            self.assertIn("one reserved child opportunity", stable_readme_words)
            self.assertIn("parent rollout continues normally", stable_readme_words)
            supergpqa_readme = (
                Path(__file__).resolve().parents[1]
                / "seeds/benchmarks/supergpqa/README.md"
            ).read_text()
            arc_readme = (
                Path(__file__).resolve().parents[1]
                / "seeds/benchmarks/arc_agi/README.md"
            ).read_text()
            self.assertIn("{submit_tool}", supergpqa_readme)
            self.assertIn("mcp__arc_agi__RESET", arc_readme)
            self.assertIn("reusable public practice/evaluation environments", arc_readme)
            self.assertIn("percentage on a 0–100 scale", arc_readme)
            self.assertNotIn("retirement from future pools", arc_readme)
            runtime_text = _format_runtime_markdown(
                instance_uuid="fixture",
                configured_problem_pool_size=None,
            )
            self.assertNotIn("solved uuids", runtime_text)
            self.assertIn("benchmark-specific", runtime_text)

    def test_outcomes_scoring_finalization_and_idempotent_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = self.make_driver(root, cap=None)
            batch = driver.prepare_batch(0, root / "shared")
            record = batch.private[0]
            events_path = root / "benchmark-events.jsonl"
            instance = "instance"
            events_path.touch()
            context = {
                "instance_uuid": instance,
                "benchmark_events_path": str(events_path),
                "generation": 0,
                "seed": 17,
                "task_index": 0,
                "rollout_index": 0,
                "rollout_username": "fixture",
                "problem_pool_records": [
                    {
                        "task_index": record.task_index,
                        "task_id": record.task_id,
                        "problem_uid": record.problem_uid,
                        "task_markdown": record.task_markdown,
                        "private_problem_path": str(record.private_problem_path),
                    }
                ],
            }
            wrong = submit_solution(context=context, args={"uuid": record.problem_uid, "answer": "A"})
            correct = submit_solution(context=context, args={"uuid": record.problem_uid, "answer": "B"})
            duplicate = submit_solution(context=context, args={"uuid": record.problem_uid, "answer": "B"})
            self.assertFalse(wrong["correct"])
            self.assertTrue(correct["correct"])
            self.assertTrue(duplicate["correct"])
            item_ref = active_benchmark_item(context)
            self.assertEqual(
                item_ref,
                BenchmarkItemRef(record.problem_uid, record.task_id, record.task_index, 0),
            )
            event_text = events_path.read_text(encoding="utf-8")
            generic_projection = item_ref.to_metadata() if item_ref is not None else {}
            self.assertNotIn("answer", json.dumps(generic_projection))
            self.assertNotIn(str(record.private_problem_path), json.dumps(generic_projection))
            self.assertIn('"benchmark_item"', event_text)
            outcome = driver.collect_outcome(batch, instance_uuid=instance, context=context)
            self.assertIsInstance(outcome, BenchmarkOutcome)
            self.assertTrue(outcome.solved)
            final = driver.finalize_batch(batch, [outcome])
            self.assertEqual(final["solved_item_ids"], [record.problem_uid])
            resumed = self.make_driver(root, cap=None).prepare_batch(1, root / "shared2")
            self.assertNotIn(record.problem_uid, [item.problem_uid for item in resumed.private])
            driver.close()
            driver.close()
            with self.assertRaisesRegex(RuntimeError, "closed"):
                driver.prepare_batch(2, root / "shared3")

    def test_historical_and_future_driver_item_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = self.make_driver(root)
            batch = driver.prepare_batch(2, root / "shared")
            record = batch.private[0]
            events_path = root / "benchmark-events.jsonl"
            instance = "historical-instance"
            append_benchmark_event(
                events_path,
                event_type="solution_scored",
                instance_uuid=instance,
                metadata={
                    "problem_uid": record.problem_uid,
                    "task_id": record.task_id,
                    "problem_task_index": record.task_index,
                    "private_problem_path": str(record.private_problem_path),
                    "submitted_answer": "private",
                },
            )
            rollout = driver.prepare_rollout(
                batch,
                backend="codex",
                context={
                    "continuation_context_path": str(root / "context.json"),
                    "benchmark_events_path": str(events_path),
                    "instance_uuid": instance,
                },
            )
            historical = _spawn_item_ref(rollout.context)
            self.assertEqual(historical.item_id, record.problem_uid)
            self.assertEqual(historical.source_id, record.task_id)
            self.assertNotIn("private", json.dumps(historical.to_metadata()))

            future_context = {
                "task_id": "scheduler-placeholder",
                "task_index": 9,
                "instance_uuid": "future-parent",
                "rollout_username": "future-rollout",
                "rollout_index": 3,
                "spawn_slots_path": str(root / "slots.json"),
                "spawn_slots_dir": str(root / "slots"),
                "population_size": 4,
                "active_benchmark_item": BenchmarkItemRef(
                    "arc-instance-42", "arc-task", 7, 9
                ).to_metadata(),
            }
            self.assertEqual(
                _spawn_item_ref(future_context),
                BenchmarkItemRef("arc-instance-42", "arc-task", 7, 9),
            )
            child_workspace = root / "child-workspace"
            child_workspace.mkdir()
            (child_workspace / "README.md").write_text("# Child\n")
            spawned = _record_spawned_child(
                context=future_context,
                child_instance_uuid="future-child",
                child_prompt="continue",
                source_workspace_dir=child_workspace,
            )
            self.assertTrue(spawned["child_spawned"])
            manifest = json.loads(
                (root / "slots" / "slot_003_future-c" / "slot_manifest.json").read_text()
            )
            self.assertEqual(
                manifest["source_benchmark_item"],
                BenchmarkItemRef("arc-instance-42", "arc-task", 7, 9).to_metadata(),
            )

    def test_prepare_failure_discards_archive_worktree_and_top_level_closes_driver(self) -> None:
        class FailingDriver:
            def __init__(self) -> None:
                self.close_calls = 0

            def prepare_rollout(self) -> None:
                raise RuntimeError("fixture prepare failure")

            def close(self) -> None:
                self.close_calls += 1

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            worktrees = root / "worktrees"
            lock = threading.Lock()
            ensure_local_world_repo(archive)
            branch = "rollout/fixture-prepare-failure"
            worktree = create_archive_worktree(
                archive_repo_dir=archive,
                worktree_root=worktrees,
                branch=branch,
                git_lock=lock,
            )
            driver = FailingDriver()
            try:
                driver.prepare_rollout()
            except RuntimeError:
                discard_archive_worktree(
                    archive_repo_dir=archive,
                    worktree_root=worktrees,
                    branch=branch,
                    git_lock=lock,
                )
            self.assertFalse(worktree.path.exists())
            branches = subprocess.run(
                ["git", "branch", "--list", branch],
                cwd=archive,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertEqual(branches.strip(), "")
            worktree_listing = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=archive,
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            self.assertNotIn(str(worktree.path), worktree_listing)

            def fail_after_driver_registration(active_drivers):
                active_drivers.append(driver)
                raise RuntimeError("fixture main failure")

            with patch.object(main_loop, "_run_main", side_effect=fail_after_driver_registration):
                with self.assertRaisesRegex(RuntimeError, "fixture main failure"):
                    main_loop.main()
            self.assertEqual(driver.close_calls, 1)


if __name__ == "__main__":
    unittest.main()

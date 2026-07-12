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
    _claim_spawn_slot,
    _format_runtime_markdown,
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
from utils.budget_ledger import append_budget_event
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
                solve_reward_token_credit_tokens=50,
                queue_path=root / "queue.json",
                task_store_dir=root / "private",
                dataset_cache_dir=root / "cache",
                backend=backend,
            ),
            rows=ROWS,
        )

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
                "budget_ledger_events": str(root / "ledger.jsonl"),
            }
            codex = driver.prepare_rollout(first, backend="codex", context=base)
            self.assertIsInstance(codex, RolloutBenchmark)
            self.assertEqual(set(codex.mcp_servers), {"supergpqa"})
            self.assertEqual(codex.mcp_budget_reconcile_tools, (("supergpqa", "submit_solution"),))
            self.assertIn(
                "mcp__supergpqa__submit_solution",
                codex.model_metadata["instructions"],
            )
            self.assertIn("spawn_child", codex.model_metadata["instructions"])
            self.assertNotIn("answer", json.dumps(codex.context["problem_pool_records"]))
            self.assertIn("mcp__supergpqa__submit_solution", (root / "shared" / "problem_pool.md").read_text())
            open_root = root / "openrouter"
            open_driver = self.make_driver(open_root, backend="openrouter")
            open_batch = open_driver.prepare_batch(4, open_root / "shared")
            openrouter = open_driver.prepare_rollout(open_batch, backend="openrouter", context=base)
            self.assertFalse(openrouter.mcp_servers)
            self.assertIn(
                "submit_solution(uuid=", openrouter.model_metadata["instructions"]
            )
            self.assertIn("submit_solution(uuid=", (open_root / "shared" / "problem_pool.md").read_text())
            self.assertNotIn("mcp__", (open_root / "shared" / "problem_pool.md").read_text())
            stable_readme = (
                Path(__file__).resolve().parents[1] / "seeds/bootstrap/README.md"
            ).read_text()
            self.assertNotIn("SuperGPQA", stable_readme)
            self.assertNotIn("submit_solution", stable_readme)
            self.assertIn("Benchmark-specific tools", stable_readme)
            self.assertIn("spawn_child", stable_readme)
            runtime_text = _format_runtime_markdown(
                instance_uuid="fixture",
                rollout_token_budget_tokens=100,
                configured_problem_pool_size=None,
            )
            self.assertNotIn("credited", runtime_text)
            self.assertNotIn("solved uuids", runtime_text)
            self.assertIn("benchmark-specific", runtime_text)

    def test_outcomes_duplicate_credit_finalization_and_idempotent_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = self.make_driver(root, cap=None)
            batch = driver.prepare_batch(0, root / "shared")
            record = batch.private[0]
            ledger = root / "ledger.jsonl"
            instance = "instance"
            append_budget_event(ledger, event_type="instance_created", instance_uuid=instance, metadata={"rollout_token_budget_tokens": 100})
            context = {
                "instance_uuid": instance,
                "budget_ledger_events": str(ledger),
                "solve_reward_token_credit_tokens": 50,
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
            self.assertEqual(correct["credited_tokens"], 50)
            self.assertEqual(duplicate["credited_tokens"], 0)
            item_ref = active_benchmark_item(context)
            self.assertEqual(
                item_ref,
                BenchmarkItemRef(record.problem_uid, record.task_id, record.task_index, 0),
            )
            event_text = ledger.read_text(encoding="utf-8")
            generic_projection = item_ref.to_metadata() if item_ref is not None else {}
            self.assertNotIn("answer", json.dumps(generic_projection))
            self.assertNotIn(str(record.private_problem_path), json.dumps(generic_projection))
            self.assertIn('"benchmark_item"', event_text)
            outcome = driver.collect_outcome(batch, instance_uuid=instance, context=context)
            self.assertIsInstance(outcome, BenchmarkOutcome)
            self.assertTrue(outcome.solved)
            self.assertEqual(outcome.metadata["credit_tokens"], 50)
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
            ledger = root / "ledger.jsonl"
            instance = "historical-instance"
            append_budget_event(
                ledger,
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
                    "budget_ledger_events": str(ledger),
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
                "child_slot_cap": 2,
                "minimum_child_budget_tokens": 10,
                "active_benchmark_item": BenchmarkItemRef(
                    "arc-instance-42", "arc-task", 7, 9
                ).to_metadata(),
            }
            self.assertEqual(
                _spawn_item_ref(future_context),
                BenchmarkItemRef("arc-instance-42", "arc-task", 7, 9),
            )
            claimed = _claim_spawn_slot(
                context=future_context,
                child_instance_uuid="future-child",
                child_prompt="continue",
                source_workspace_dir=None,
                initial_budget_tokens=10,
                parent_budget={"remaining_tokens": 100},
            )
            self.assertTrue(claimed["slot_claimed"])
            manifest = json.loads(
                (root / "slots" / "slot_000_future-c" / "slot_manifest.json").read_text()
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

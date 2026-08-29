from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import main_loop
from main_loop import (
    CODEX_READ_README_BASE_INSTRUCTIONS,
    READ_README_TASK_INSTRUCTIONS,
    WorkerResult,
    _run_main,
    _spawn_child_continuation,
    create_archive_worktree,
    discard_archive_worktree,
    ensure_local_world_repo,
    finalize_archive_worktree,
)
from utils.codex_runner import run_codex_rollout


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_TASK = (
    "# Task\n\n"
    "Prove the Riemann hypothesis.\n\n"
    "The Riemann hypothesis states that every nontrivial zero of the analytically\n"
    "continued Riemann zeta function ζ(s) has real part 1/2.\n"
).encode("utf-8")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


class HistoricalV1Tests(unittest.TestCase):
    def test_exact_preserved_prompt_readme_and_task_bytes(self) -> None:
        self.assertEqual(
            READ_README_TASK_INSTRUCTIONS,
            "This rollout has no assigned task. README.md describes its environment.",
        )
        self.assertEqual(CODEX_READ_README_BASE_INSTRUCTIONS, READ_README_TASK_INSTRUCTIONS)
        self.assertEqual(len(READ_README_TASK_INSTRUCTIONS.encode("utf-8")), 71)
        self.assertEqual(
            hashlib.sha256(READ_README_TASK_INSTRUCTIONS.encode("utf-8")).hexdigest(),
            "ae48d75abfdaedb43a7b650b7430c0eaefc9338fa92cc62f99d55493aa132063",
        )
        readme = (PROJECT_ROOT / "seeds/bootstrap/README.md").read_bytes()
        self.assertEqual(len(readme), 4011)
        self.assertEqual(
            hashlib.sha256(readme).hexdigest(),
            "5351d015c65a36cc8fc652a0acbd180cac573783b3b0b67c264b4ca333aa76d8",
        )
        self.assertEqual(len(HISTORICAL_TASK), 173)
        self.assertEqual(
            hashlib.sha256(HISTORICAL_TASK).hexdigest(),
            "d112892c81d5a637f847128ca1ed713bbc962382c082774c46387df5df9ed2ef",
        )

    def test_codex_request_boundary_and_historical_completion_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_runner = root / "fake-codex-runner"
            fake_runner.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.load(sys.stdin)\n"
                "print(json.dumps({'event':'thread_started','thread_id':'thr_v1','session_id':'ses_v1'}), flush=True)\n"
                "print(json.dumps({'event':'turn_started','turn_id':'turn_v1'}), flush=True)\n"
                "print(json.dumps({'event':'turn_complete','turn_id':'turn_v1','final_text':'historical final'}), flush=True)\n",
                encoding="utf-8",
            )
            fake_runner.chmod(0o755)

            archive = root / "archive"
            ensure_local_world_repo(archive)
            worktree = create_archive_worktree(
                archive_repo_dir=archive,
                worktree_root=root / "worktrees",
                branch="rollout/request-boundary",
                git_lock=threading.Lock(),
            )
            workdir = root / "rollout"
            seed_output = workdir / "seed_output"
            shared = root / "shared"
            state = root / "state"
            control = root / "control"
            codex_home = root / "codex-home"
            for path in (workdir, seed_output, shared, state, codex_home):
                path.mkdir(parents=True, exist_ok=True)
            continuation = control / "continuation_context.json"
            continuation.parent.mkdir(parents=True)
            continuation.write_text("{}\n", encoding="utf-8")

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", ResourceWarning)
                    result = run_codex_rollout(
                        runner_bin=fake_runner,
                        model="gpt-5.6-sol",
                        workdir=workdir,
                        control_dir=control,
                        worker_state_dir=state,
                        codex_home=codex_home,
                        seed_output_dir=seed_output,
                        archive_repo_dir=worktree.path,
                        archive_git_dir=archive / ".git",
                        shared_workspace_dir=shared,
                        rollout_username="rollout_user_000",
                        timeout_seconds=60,
                        sandbox_mode="workspace-write",
                        initial_user_text=READ_README_TASK_INSTRUCTIONS,
                        base_instructions=CODEX_READ_README_BASE_INSTRUCTIONS,
                        spawn_child_handler_context_path=continuation,
                    )
                request = json.loads((control / "codex_runner.request.json").read_text())
                expected_keys = {
                    "additional_writable_roots",
                    "base_instructions",
                    "codex_home",
                    "cwd",
                    "initial_user_text",
                    "model",
                    "sandbox_mode",
                    "spawn_child_handler_command",
                    "timeout_seconds",
                    "workspace_roots",
                }
                self.assertEqual(set(request), expected_keys)
                self.assertEqual(request["base_instructions"], READ_README_TASK_INSTRUCTIONS)
                self.assertEqual(request["initial_user_text"], READ_README_TASK_INSTRUCTIONS)
                self.assertEqual(
                    request["workspace_roots"],
                    [str(workdir), str(seed_output), str(worktree.path), str(shared), str(state)],
                )
                git_dir = _git(worktree.path, "rev-parse", "--absolute-git-dir").stdout.strip()
                self.assertEqual(
                    request["additional_writable_roots"],
                    [
                        str(seed_output),
                        str(worktree.path),
                        str(shared),
                        str(state),
                        git_dir,
                        str(archive / ".git"),
                    ],
                )
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["stop_reason"], "final_message")
                self.assertEqual(result["final_text"], "historical final")
                self.assertNotIn("system_instructions", request)
                self.assertFalse(any("peer" in key or "cgroup" in key for key in request))
            finally:
                discard_archive_worktree(
                    archive_repo_dir=archive,
                    worktree_root=root / "worktrees",
                    branch=worktree.branch,
                    git_lock=threading.Lock(),
                )

    def test_provider_free_task0_and_task1_lineage_and_archive_path(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=documents) as temp:
            root = Path(temp)
            runtime = root / "runtime"
            task = root / "riemann_hypothesis.md"
            task.write_bytes(HISTORICAL_TASK)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            calls: list[dict[str, object]] = []
            failures: list[str] = []
            calls_lock = threading.Lock()

            def worker(**kwargs: object) -> WorkerResult:
                context = json.loads(
                    Path(str(kwargs["continuation_context_path"])).read_text()
                )
                task_index = int(context["task_index"])
                rollout_index = int(context["rollout_index"])
                workdir = Path(str(kwargs["workdir"]))
                archive = Path(str(kwargs["archive_repo_dir"]))
                try:
                    self.assertEqual(kwargs["base_instructions"], READ_README_TASK_INSTRUCTIONS)
                    self.assertEqual((workdir / "README.md").read_bytes(), (
                        PROJECT_ROOT / "seeds/bootstrap/README.md"
                    ).read_bytes() if task_index == 0 else f"# Child {rollout_index}\n".encode())
                    if task_index == 0:
                        self.assertEqual(kwargs["initial_user_text"], READ_README_TASK_INSTRUCTIONS)
                    else:
                        self.assertEqual(
                            kwargs["initial_user_text"],
                            f"Continue lineage {rollout_index}",
                        )
                        self.assertEqual(
                            (workdir / "lineage.txt").read_text(),
                            f"parent {rollout_index}\n",
                        )
                    archive_file = archive / f"task-{task_index}-rollout-{rollout_index}.txt"
                    archive_file.write_text("committed\n", encoding="utf-8")
                    (archive / "uncommitted.tmp").write_text("discard me\n", encoding="utf-8")
                    _git(archive, "add", archive_file.name)
                    _git(archive, "commit", "-m", f"task {task_index} rollout {rollout_index}")
                    if task_index == 0:
                        child = workdir / "child"
                        child.mkdir()
                        (child / "README.md").write_text(
                            f"# Child {rollout_index}\n", encoding="utf-8"
                        )
                        (child / "lineage.txt").write_text(
                            f"parent {rollout_index}\n", encoding="utf-8"
                        )
                        spawned = _spawn_child_continuation(
                            context=context,
                            args={
                                "prompt": f"Continue lineage {rollout_index}",
                                "workspace_dir": "child",
                            },
                        )
                        self.assertTrue(spawned["child_spawned"])
                        self.assertTrue(spawned["parent_continues"])
                    with calls_lock:
                        calls.append(
                            {
                                "task_index": task_index,
                                "rollout_index": rollout_index,
                                "workdir": str(workdir),
                                "archive": str(archive),
                            }
                        )
                except BaseException as exc:
                    with calls_lock:
                        failures.append(f"task={task_index} rollout={rollout_index}: {exc}")
                    raise
                return WorkerResult("offline final", "completed", "final_message")

            argv = [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                str(task),
                "--runtime-root",
                str(runtime),
                "--worker-backend",
                "codex",
                "--model",
                "gpt-5.6-sol",
                "--num-rollouts",
                "2",
                "--step",
                "--codex-runner-bin",
                "/bin/true",
                "--codex-home",
                str(codex_home),
            ]
            for _ in range(2):
                with patch("sys.argv", argv), patch(
                    "main_loop.run_codex_worker", side_effect=worker
                ):
                    _run_main([])

            self.assertEqual(failures, [])
            self.assertEqual(len(calls), 4)
            by_task = {
                task_index: sorted(
                    (call for call in calls if call["task_index"] == task_index),
                    key=lambda call: int(call["rollout_index"]),
                )
                for task_index in (0, 1)
            }
            for task_calls in by_task.values():
                self.assertEqual(len({call["workdir"] for call in task_calls}), 2)
                self.assertEqual(len({call["archive"] for call in task_calls}), 2)
            records = [
                json.loads(line)
                for line in (runtime / "logs/runs.jsonl").read_text().splitlines()
            ]
            self.assertEqual([(r["task_index"], r["rollout_index"]) for r in records], [
                (0, 0), (0, 1), (1, 0), (1, 1)
            ])
            self.assertTrue(all(r["worker_status"] == "completed" for r in records))
            self.assertTrue(all(r["worker_stop_reason"] == "final_message" for r in records))
            self.assertTrue(all(not any(k.startswith("opencode_") for k in r) for r in records))
            self.assertEqual((runtime / "logs/open_ended_task/task.md").read_bytes(), HISTORICAL_TASK)
            self.assertEqual(
                (
                    runtime
                    / "logs/tmp/rollout_chain/shared_workspace/BENCHMARK.md"
                ).read_bytes(),
                HISTORICAL_TASK,
            )
            archive = runtime / "archive/world_repo"
            for task_index in (0, 1):
                for rollout_index in (0, 1):
                    self.assertTrue(
                        (archive / f"task-{task_index}-rollout-{rollout_index}.txt").is_file()
                    )
            self.assertFalse((archive / "uncommitted.tmp").exists())
            self.assertEqual(_git(archive, "status", "--porcelain").stdout, "")
            self.assertFalse(any("peer_message" in path.name for path in runtime.rglob("*")))

    def test_eight_linked_worktrees_and_historical_conflict_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            worktree_root = root / "worktrees"
            ensure_local_world_repo(archive)
            lock = threading.Lock()
            worktrees = [
                create_archive_worktree(
                    archive_repo_dir=archive,
                    worktree_root=worktree_root,
                    branch=f"rollout/fixture-{index}",
                    git_lock=lock,
                )
                for index in range(8)
            ]
            try:
                self.assertEqual(len({str(w.path) for w in worktrees}), 8)
                self.assertEqual(
                    len({_git(w.path, "rev-parse", "--absolute-git-dir").stdout.strip() for w in worktrees}),
                    8,
                )
                for index, worktree in enumerate(worktrees):
                    (worktree.path / "collision.txt").write_text(
                        f"rollout {index}\n", encoding="utf-8"
                    )
                    _git(worktree.path, "add", "collision.txt")
                    _git(worktree.path, "commit", "-m", f"rollout {index}")

                first = finalize_archive_worktree(
                    archive_repo_dir=archive,
                    worktree=worktrees[0],
                    git_lock=lock,
                )
                conflicted = finalize_archive_worktree(
                    archive_repo_dir=archive,
                    worktree=worktrees[1],
                    git_lock=lock,
                )
                self.assertTrue(first["archive_merged"])
                self.assertFalse(conflicted["archive_merged"])
                self.assertIn("archive_merge_error", conflicted)
                self.assertEqual((archive / "collision.txt").read_text(), "rollout 0\n")
                self.assertEqual(
                    _git(
                        archive,
                        "show-ref",
                        "--verify",
                        f"refs/heads/{worktrees[1].branch}",
                        check=False,
                    ).returncode,
                    0,
                )
                self.assertFalse(worktrees[1].path.exists())
            finally:
                for worktree in worktrees[2:]:
                    discard_archive_worktree(
                        archive_repo_dir=archive,
                        worktree_root=worktree_root,
                        branch=worktree.branch,
                        git_lock=lock,
                    )


if __name__ == "__main__":
    unittest.main()

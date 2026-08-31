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
    ArchiveConflictResolver,
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


class V36ConflictResolutionTests(unittest.TestCase):
    def _root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def _conflict(self) -> tuple[Path, threading.Lock, main_loop.ArchiveWorktree, str]:
        root = self._root()
        archive = root / "archive"
        ensure_local_world_repo(archive)
        (archive / "collision.txt").write_text("base\n", encoding="utf-8")
        _git(archive, "add", "collision.txt")
        _git(archive, "commit", "-m", "collision base")
        lock = threading.Lock()
        first = create_archive_worktree(
            archive_repo_dir=archive,
            worktree_root=root / "worktrees",
            branch="rollout/first",
            git_lock=lock,
        )
        conflicted = create_archive_worktree(
            archive_repo_dir=archive,
            worktree_root=root / "worktrees",
            branch="rollout/conflicted",
            git_lock=lock,
        )
        for worktree, text in ((first, "first\n"), (conflicted, "second\n")):
            (worktree.path / "collision.txt").write_text(text, encoding="utf-8")
            _git(worktree.path, "add", "collision.txt")
            _git(worktree.path, "commit", "-m", text.strip())
        self.assertTrue(
            finalize_archive_worktree(
                archive_repo_dir=archive,
                worktree=first,
                git_lock=lock,
            )["archive_merged"]
        )
        original_head = _git(conflicted.path, "rev-parse", "HEAD").stdout.strip()
        return archive, lock, conflicted, original_head

    def _resolver(
        self,
        worktree: main_loop.ArchiveWorktree,
        resume: object,
        *,
        rollout_path: bool = True,
    ) -> ArchiveConflictResolver:
        session_path = worktree.path.parent / "session.jsonl"
        if rollout_path:
            session_path.write_text("{}\n", encoding="utf-8")
        return ArchiveConflictResolver(
            backend="codex",
            rollout_path=session_path if rollout_path else None,
            thread_id="thread-original",
            session_id="session-original",
            resume_turn=resume,
        )

    @staticmethod
    def _completed() -> WorkerResult:
        return WorkerResult(
            final_text="done",
            status="completed",
            stop_reason="final_message",
            metadata={
                "thread_id": "thread-original",
                "session_id": "session-original",
                "turn_count": 1,
                "tool_call_count": 3,
                "spawn_child_tool_call_count": 0,
                "turn_completed": True,
            },
        )

    def test_v36_clean_merge_skips_turn_and_exact_session_merge_succeeds(self) -> None:
        root = self._root()
        archive = root / "clean-archive"
        ensure_local_world_repo(archive)
        lock = threading.Lock()
        clean = create_archive_worktree(
            archive_repo_dir=archive,
            worktree_root=root / "clean-worktrees",
            branch="rollout/clean",
            git_lock=lock,
        )
        (clean.path / "clean.txt").write_text("clean\n", encoding="utf-8")
        _git(clean.path, "add", "clean.txt")
        _git(clean.path, "commit", "-m", "clean")
        calls = 0

        def unexpected() -> WorkerResult:
            nonlocal calls
            calls += 1
            return self._completed()

        clean_result = finalize_archive_worktree(
            archive_repo_dir=archive,
            worktree=clean,
            git_lock=lock,
            conflict_resolver=self._resolver(clean, unexpected),
        )
        self.assertTrue(clean_result["archive_merged"])
        self.assertFalse(clean_result["archive_resolution_attempted"])
        self.assertEqual(calls, 0)

        archive, lock, conflicted, original_head = self._conflict()
        canonical_before = _git(archive, "rev-parse", "HEAD").stdout.strip()

        def resolve() -> WorkerResult:
            self.assertTrue(_git(conflicted.path, "ls-files", "-u").stdout)
            (conflicted.path / "collision.txt").write_text(
                "first and second\n", encoding="utf-8"
            )
            _git(conflicted.path, "add", "collision.txt")
            _git(conflicted.path, "commit", "--no-edit")
            return self._completed()

        resolved = finalize_archive_worktree(
            archive_repo_dir=archive,
            worktree=conflicted,
            git_lock=lock,
            conflict_resolver=self._resolver(conflicted, resolve),
        )
        self.assertTrue(resolved["archive_resolution_succeeded"])
        self.assertEqual(resolved["archive_resolution_attempt_count"], 1)
        self.assertEqual(resolved["archive_resolution_turn_count"], 1)
        self.assertEqual(resolved["archive_resolution_tool_call_count"], 3)
        self.assertEqual(resolved["archive_resolution_spawn_child_tool_call_count"], 0)
        resolved_head = _git(archive, "rev-parse", "HEAD").stdout.strip()
        parents = _git(archive, "rev-list", "--parents", "-n", "1", resolved_head).stdout.split()
        self.assertEqual(parents[1:], [canonical_before, original_head])
        self.assertEqual(_git(archive, "status", "--porcelain").stdout, "")

    def test_v36_failures_retain_original_ref_and_attempt_at_most_once(self) -> None:
        cases = {
            "unsupported": "resolver_unsupported",
            "missing": "resolver_session_missing_or_unsupported",
            "resume_error": "resolver_turn_failed",
            "timeout": "resolver_timeout",
            "decline_unmerged": "resolver_left_unmerged_entries",
            "dirty_no_commit": "resolver_left_dirty_worktree",
            "discarded_parent": "resolver_merge_structure_invalid",
        }
        for mode, expected_error in cases.items():
            with self.subTest(mode=mode):
                archive, lock, conflicted, original_head = self._conflict()
                calls = 0

                def resume() -> WorkerResult:
                    nonlocal calls
                    calls += 1
                    if mode == "resume_error":
                        return WorkerResult("", "error", "fixture", metadata={})
                    if mode == "timeout":
                        return WorkerResult("", "timeout", "fixture", metadata={})
                    if mode == "dirty_no_commit":
                        (conflicted.path / "collision.txt").write_text(
                            "staged\n", encoding="utf-8"
                        )
                        _git(conflicted.path, "add", "collision.txt")
                    elif mode == "discarded_parent":
                        _git(conflicted.path, "merge", "--abort")
                        _git(
                            conflicted.path,
                            "commit",
                            "--allow-empty",
                            "-m",
                            "not a merge",
                        )
                    return self._completed()

                if mode == "unsupported":
                    resolver = None
                else:
                    resolver = self._resolver(
                        conflicted,
                        resume,
                        rollout_path=mode != "missing",
                    )
                result = finalize_archive_worktree(
                    archive_repo_dir=archive,
                    worktree=conflicted,
                    git_lock=lock,
                    conflict_resolver=resolver,
                )
                self.assertTrue(result["archive_resolution_fell_back"])
                self.assertEqual(result["archive_resolution_error"], expected_error)
                self.assertLessEqual(calls, 1)
                self.assertEqual(calls, 0 if mode in {"unsupported", "missing"} else 1)
                self.assertEqual(
                    _git(
                        archive,
                        "show-ref",
                        "--hash",
                        "--verify",
                        f"refs/heads/{conflicted.branch}",
                    ).stdout.strip(),
                    original_head,
                )
                self.assertEqual(_git(archive, "status", "--porcelain").stdout, "")

    def test_v36_later_branch_continues_after_fallback(self) -> None:
        archive, lock, conflicted, original_head = self._conflict()
        later = create_archive_worktree(
            archive_repo_dir=archive,
            worktree_root=conflicted.path.parent,
            branch="rollout/later",
            git_lock=lock,
        )
        (later.path / "later.txt").write_text("later\n", encoding="utf-8")
        _git(later.path, "add", "later.txt")
        _git(later.path, "commit", "-m", "later")
        failed = finalize_archive_worktree(
            archive_repo_dir=archive,
            worktree=conflicted,
            git_lock=lock,
        )
        succeeded = finalize_archive_worktree(
            archive_repo_dir=archive,
            worktree=later,
            git_lock=lock,
        )
        self.assertTrue(failed["archive_original_ref_preserved"])
        self.assertEqual(failed["archive_original_ref_commit"], original_head)
        self.assertTrue(succeeded["archive_merged"])
        self.assertTrue((archive / "later.txt").is_file())

    def test_v36_main_integrates_by_slot_after_all_research_turns(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=documents) as temp:
            root = Path(temp)
            task = root / "task.md"
            task.write_text("# Offline integration order\n", encoding="utf-8")
            codex_home = root / "codex-home"
            codex_home.mkdir()
            second_finished = threading.Event()
            finish_order: list[int] = []

            def worker(**kwargs: object) -> WorkerResult:
                context = json.loads(
                    Path(str(kwargs["continuation_context_path"])).read_text()
                )
                index = int(context["rollout_index"])
                archive = Path(str(kwargs["archive_repo_dir"]))
                (archive / "ordered.txt").write_text(
                    f"rollout {index}\n", encoding="utf-8"
                )
                _git(archive, "add", "ordered.txt")
                _git(archive, "commit", "-m", f"rollout {index}")
                self.assertTrue(kwargs["persist_session"])
                if index == 0:
                    self.assertTrue(second_finished.wait(timeout=5))
                else:
                    second_finished.set()
                finish_order.append(index)
                return WorkerResult("offline", "completed", "final_message", metadata={})

            argv = [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                str(task),
                "--runtime-root",
                str(root / "runtime"),
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
            with patch("sys.argv", argv), patch(
                "main_loop.run_codex_worker", side_effect=worker
            ):
                _run_main([])
            self.assertEqual(finish_order, [1, 0])
            archive = root / "runtime/archive/world_repo"
            self.assertEqual((archive / "ordered.txt").read_text(), "rollout 0\n")
            records = [
                json.loads(line)
                for line in (root / "runtime/logs/runs.jsonl").read_text().splitlines()
            ]
            self.assertTrue(records[0]["archive_merged"])
            self.assertEqual(
                records[1]["archive_resolution_error"],
                "resolver_session_missing_or_unsupported",
            )

    def test_v36_resolution_request_resumes_exact_identity_without_child_tool(self) -> None:
        root = self._root()
        fake_runner = root / "fake-runner"
        fake_runner.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "request = json.load(sys.stdin)\n"
            "print(json.dumps({'event':'thread_started','thread_id':request['expected_thread_id'],'session_id':request['expected_session_id'],'resumed':True}), flush=True)\n"
            "print(json.dumps({'event':'turn_started','turn_id':'resolution-turn'}), flush=True)\n"
            "print(json.dumps({'event':'tool_begin','tool':'exec_command','call_id':'one'}), flush=True)\n"
            "print(json.dumps({'event':'tool_end','tool':'exec_command','call_id':'one','exit_code':0}), flush=True)\n"
            "print(json.dumps({'event':'turn_complete','turn_id':'resolution-turn','final_text':'done'}), flush=True)\n",
            encoding="utf-8",
        )
        fake_runner.chmod(0o755)
        archive = root / "archive"
        ensure_local_world_repo(archive)
        session_path = root / "session.jsonl"
        session_path.write_text("{}\n", encoding="utf-8")
        paths = [
            root / name
            for name in ("work", "control", "state", "codex", "seed", "shared")
        ]
        for path in paths:
            path.mkdir()
        result = run_codex_rollout(
            runner_bin=fake_runner,
            model="gpt-5.6-sol",
            workdir=paths[0],
            control_dir=paths[1],
            worker_state_dir=paths[2],
            codex_home=paths[3],
            seed_output_dir=paths[4],
            archive_repo_dir=archive,
            archive_git_dir=archive / ".git",
            shared_workspace_dir=paths[5],
            rollout_username="rollout_user_000",
            timeout_seconds=5,
            resume_rollout_path=session_path,
            expected_thread_id="thread-original",
            expected_session_id="session-original",
            resolution_phase=True,
        )
        request = json.loads((paths[1] / "codex_runner.request.json").read_text())
        self.assertTrue(request["resolution_phase"])
        self.assertNotIn("spawn_child_handler_command", request)
        self.assertNotIn("mcp_servers", request)
        self.assertEqual(result["thread_id"], "thread-original")
        self.assertEqual(result["session_id"], "session-original")
        self.assertEqual(result["turn_count"], 1)
        self.assertEqual(result["tool_call_count"], 1)
        self.assertEqual(result["spawn_child_tool_call_count"], 0)
        self.assertTrue(result["turn_completed"])


if __name__ == "__main__":
    unittest.main()

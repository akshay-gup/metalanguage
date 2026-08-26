from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import main_loop
from main_loop import (
    LEGACY_SHARED_GIT_FINGERPRINT,
    LEGACY_SHARED_GIT_VERSION,
    SHARED_GIT_DIRNAME,
    SHARED_GIT_FINGERPRINT,
    SHARED_GIT_VERSION,
    _cleanup_rollout_shared_writes,
    _run_bash_tool,
    _shared_git_operation_state,
    _shared_git_repo_identity,
    _shared_git_resume_compatible,
    _snapshot_workspace_files,
    clean_shared_git_repo,
    ensure_shared_git_repo,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _regular_file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class SharedGitTests(unittest.TestCase):
    def test_legacy_repo_is_rehomed_without_changing_tree_index_refs_or_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "archive/world_repo"
            ensure_shared_git_repo(legacy)
            (legacy / "tracked.txt").write_text("staged\n", encoding="utf-8")
            _git(legacy, "add", "tracked.txt")
            (legacy / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            _git(legacy, "branch", "historical-ref")
            before_inode = legacy.stat().st_ino
            before_status = _git(legacy, "status", "--porcelain=v1")
            before_refs = _git(legacy, "for-each-ref", "--format=%(refname) %(objectname)")
            before_hashes = _regular_file_hashes(legacy)

            shared_root = root / "logs/tmp/rollout_chain/shared_workspace"
            shared_repo = shared_root / SHARED_GIT_DIRNAME
            result = ensure_shared_git_repo(
                shared_repo,
                legacy_repo_path=legacy,
            )

            self.assertTrue(result["migrated"])
            self.assertTrue(legacy.is_symlink())
            self.assertEqual(legacy.resolve(), shared_repo.resolve())
            self.assertEqual(shared_repo.stat().st_ino, before_inode)
            self.assertEqual(_git(shared_repo, "status", "--porcelain=v1"), before_status)
            self.assertEqual(
                _git(shared_repo, "for-each-ref", "--format=%(refname) %(objectname)"),
                before_refs,
            )
            self.assertEqual(_regular_file_hashes(shared_repo), before_hashes)

            second = ensure_shared_git_repo(
                shared_repo,
                legacy_repo_path=legacy,
            )
            self.assertFalse(second["migrated"])
            self.assertFalse(second["initialized"])

    def test_rollouts_share_checkout_inode_while_private_roots_stay_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared = root / "shared_workspace"
            repo = shared / SHARED_GIT_DIRNAME
            ensure_shared_git_repo(repo)
            workdirs = [root / f"rollout-{index}" for index in range(16)]
            for workdir in workdirs:
                workdir.mkdir()
                (workdir / "archive").symlink_to(repo, target_is_directory=True)
                (workdir / "shared_workspace").symlink_to(
                    shared, target_is_directory=True
                )

            self.assertEqual(len({path.stat().st_ino for path in workdirs}), 16)
            self.assertEqual(
                {(path / "archive").resolve() for path in workdirs},
                {repo.resolve()},
            )
            self.assertEqual(
                {os.stat(path / "archive").st_ino for path in workdirs},
                {repo.stat().st_ino},
            )
            self.assertEqual(
                {(path / "shared_workspace/archive").resolve() for path in workdirs},
                {repo.resolve()},
            )

    def test_batch_final_cleanup_preserves_commits_refs_head_and_removes_all_dirty_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            shared = Path(temp) / "shared_workspace"
            repo = shared / SHARED_GIT_DIRNAME
            ensure_shared_git_repo(repo)
            (shared / "BENCHMARK.md").write_text("exact task bytes\n", encoding="utf-8")
            before = _snapshot_workspace_files(
                shared,
                excluded_top_level=frozenset({SHARED_GIT_DIRNAME}),
            )

            (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
            (repo / "staged.txt").write_text("committed staged\n", encoding="utf-8")
            (repo / "unstaged.txt").write_text("committed unstaged\n", encoding="utf-8")
            (repo / "deleted.txt").write_text("committed deleted\n", encoding="utf-8")
            _git(repo, "add", ".gitignore", "staged.txt", "unstaged.txt", "deleted.txt")
            _git(repo, "commit", "-m", "cleanup fixture")
            _git(repo, "branch", "agent-created")
            expected_head = _git(repo, "rev-parse", "HEAD")
            expected_branch = _git(repo, "symbolic-ref", "HEAD")
            expected_refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")

            (repo / "staged.txt").write_text("staged edit\n", encoding="utf-8")
            _git(repo, "add", "staged.txt")
            (repo / "unstaged.txt").write_text("unstaged edit\n", encoding="utf-8")
            (repo / "deleted.txt").unlink()
            (repo / "untracked/child").mkdir(parents=True)
            (repo / "untracked/child/value.txt").write_text("remove\n", encoding="utf-8")
            (repo / "ignored").mkdir()
            (repo / "ignored/value.txt").write_text("remove ignored\n", encoding="utf-8")
            (shared / "scratch.txt").write_text("ephemeral\n", encoding="utf-8")

            _cleanup_rollout_shared_writes(shared, before)
            outcome = clean_shared_git_repo(repo, shared_workspace_dir=shared)

            self.assertFalse((shared / "scratch.txt").exists())
            self.assertEqual((shared / "BENCHMARK.md").read_bytes(), b"exact task bytes\n")
            self.assertEqual(outcome["operation_state"], None)
            self.assertGreaterEqual(outcome["discarded_status_entry_count"], 5)
            self.assertEqual(_git(repo, "status", "--porcelain=v1", "--ignored"), "")
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), expected_head)
            self.assertEqual(_git(repo, "symbolic-ref", "HEAD"), expected_branch)
            self.assertEqual(
                _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
                expected_refs,
            )
            self.assertEqual((repo / "staged.txt").read_text(), "committed staged\n")
            self.assertEqual((repo / "unstaged.txt").read_text(), "committed unstaged\n")
            self.assertEqual((repo / "deleted.txt").read_text(), "committed deleted\n")
            self.assertFalse((repo / "untracked").exists())
            self.assertFalse((repo / "ignored").exists())

    def test_cleanup_is_scoped_to_exact_archive_and_never_runs_in_a_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared = root / "shared_workspace"
            repo = shared / SHARED_GIT_DIRNAME
            ensure_shared_git_repo(repo)
            outside = root / "outside.txt"
            outside.write_text("preserve exactly\n", encoding="utf-8")
            (repo / "remove.txt").write_text("remove\n", encoding="utf-8")

            clean_shared_git_repo(repo, shared_workspace_dir=shared)

            self.assertEqual(outside.read_bytes(), b"preserve exactly\n")
            self.assertFalse((repo / "remove.txt").exists())
            with self.assertRaisesRegex(RuntimeError, "canonical shared archive"):
                clean_shared_git_repo(shared, shared_workspace_dir=shared)
            with self.assertRaisesRegex(RuntimeError, "canonical shared archive"):
                clean_shared_git_repo(root, shared_workspace_dir=shared)

    def test_replaced_archive_fails_before_cleanup_and_leaves_moved_repo_intact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            shared = Path(temp) / "shared_workspace"
            repo = shared / SHARED_GIT_DIRNAME
            ensure_shared_git_repo(repo)
            expected_identity = _shared_git_repo_identity(repo)
            (repo / "uncommitted.txt").write_text("preserve on failed identity\n")
            moved = shared / "moved-archive"
            repo.rename(moved)
            ensure_shared_git_repo(repo)
            replacement_head = _git(repo, "rev-parse", "HEAD")

            with self.assertRaisesRegex(RuntimeError, "no longer matches"):
                clean_shared_git_repo(
                    repo,
                    shared_workspace_dir=shared,
                    expected_identity=expected_identity,
                )

            self.assertEqual(
                (moved / "uncommitted.txt").read_text(),
                "preserve on failed identity\n",
            )
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), replacement_head)

    def test_cleanup_clears_merge_state_without_invoking_merge_or_changing_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            shared = Path(temp) / "shared_workspace"
            repo = shared / SHARED_GIT_DIRNAME
            ensure_shared_git_repo(repo)
            _git(repo, "checkout", "-b", "side")
            (repo / "WORLD.md").write_text("side\n", encoding="utf-8")
            _git(repo, "add", "WORLD.md")
            _git(repo, "commit", "-m", "side change")
            _git(repo, "checkout", "main")
            (repo / "WORLD.md").write_text("main\n", encoding="utf-8")
            _git(repo, "add", "WORLD.md")
            _git(repo, "commit", "-m", "main change")
            merge = subprocess.run(
                ["git", "merge", "side"], cwd=repo, capture_output=True, text=True
            )
            self.assertNotEqual(merge.returncode, 0)
            self.assertEqual(_shared_git_operation_state(repo), "merge")
            expected_head = _git(repo, "rev-parse", "HEAD")
            expected_branch = _git(repo, "symbolic-ref", "HEAD")
            expected_refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
            calls: list[tuple[str, ...]] = []
            real_run_git = main_loop._run_git

            def recording_run_git(args, cwd, *, check=True):
                calls.append(tuple(args))
                return real_run_git(args, cwd, check=check)

            with patch("main_loop._run_git", side_effect=recording_run_git):
                result = clean_shared_git_repo(repo, shared_workspace_dir=shared)

            self.assertEqual(result["operation_state"], "merge")
            self.assertIsNone(_shared_git_operation_state(repo))
            self.assertEqual(_git(repo, "status", "--porcelain=v1"), "")
            self.assertEqual(_git(repo, "rev-parse", "HEAD"), expected_head)
            self.assertEqual(_git(repo, "symbolic-ref", "HEAD"), expected_branch)
            self.assertEqual(
                _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
                expected_refs,
            )
            self.assertNotIn("merge", {args[0] for args in calls})
            self.assertFalse(
                {"commit", "worktree", "branch", "checkout"}
                & {args[0] for args in calls}
            )

    def test_cleanup_quits_rebase_cherry_pick_revert_and_am_states(self) -> None:
        for operation in ("rebase", "cherry-pick", "revert", "am"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temp:
                shared = Path(temp) / "shared_workspace"
                repo = shared / SHARED_GIT_DIRNAME
                ensure_shared_git_repo(repo)

                if operation == "rebase":
                    _git(repo, "checkout", "-b", "feature")
                    (repo / "WORLD.md").write_text("feature\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "feature")
                    _git(repo, "checkout", "main")
                    (repo / "WORLD.md").write_text("main\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "main")
                    _git(repo, "checkout", "feature")
                    command = ["rebase", "main"]
                elif operation == "cherry-pick":
                    _git(repo, "checkout", "-b", "source")
                    (repo / "WORLD.md").write_text("source\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "source")
                    source_commit = _git(repo, "rev-parse", "HEAD").strip()
                    _git(repo, "checkout", "main")
                    (repo / "WORLD.md").write_text("main\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "main")
                    command = ["cherry-pick", source_commit]
                elif operation == "revert":
                    (repo / "WORLD.md").write_text("target\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "target")
                    target_commit = _git(repo, "rev-parse", "HEAD").strip()
                    (repo / "WORLD.md").write_text("later\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "later")
                    command = ["revert", "--no-edit", target_commit]
                else:
                    _git(repo, "checkout", "-b", "mail-source")
                    (repo / "WORLD.md").write_text("mail\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "mail")
                    patch_text = _git(repo, "format-patch", "-1", "--stdout")
                    _git(repo, "checkout", "main")
                    (repo / "WORLD.md").write_text("main\n")
                    _git(repo, "add", "WORLD.md")
                    _git(repo, "commit", "-m", "main")
                    patch_path = shared / "mail.patch"
                    patch_path.write_text(patch_text)
                    command = ["am", str(patch_path)]

                conflict = subprocess.run(
                    ["git", *command], cwd=repo, capture_output=True, text=True
                )
                self.assertNotEqual(conflict.returncode, 0)
                self.assertEqual(_shared_git_operation_state(repo), operation)
                expected_head = _git(repo, "rev-parse", "HEAD")
                symbolic = subprocess.run(
                    ["git", "symbolic-ref", "-q", "HEAD"],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                )
                expected_branch = (symbolic.returncode, symbolic.stdout)
                expected_refs = _git(
                    repo, "for-each-ref", "--format=%(refname) %(objectname)"
                )

                outcome = clean_shared_git_repo(repo, shared_workspace_dir=shared)

                self.assertEqual(outcome["operation_state"], operation)
                self.assertIsNone(_shared_git_operation_state(repo))
                self.assertEqual(_git(repo, "status", "--porcelain=v1"), "")
                self.assertEqual(_git(repo, "rev-parse", "HEAD"), expected_head)
                symbolic_after = subprocess.run(
                    ["git", "symbolic-ref", "-q", "HEAD"],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    (symbolic_after.returncode, symbolic_after.stdout), expected_branch
                )
                self.assertEqual(
                    _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
                    expected_refs,
                )

    def test_operation_state_detection_and_unknown_sequencer_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = {
                "rebase": ("rebase-merge", None),
                "am": ("rebase-apply", "applying"),
                "cherry-pick": (None, "CHERRY_PICK_HEAD"),
                "revert": (None, "REVERT_HEAD"),
                "merge": (None, "MERGE_HEAD"),
            }
            for index, (expected, (directory, marker)) in enumerate(cases.items()):
                repo = root / str(index)
                git_dir = repo / ".git"
                git_dir.mkdir(parents=True)
                if directory is not None:
                    (git_dir / directory).mkdir()
                if marker is not None:
                    marker_path = (
                        git_dir / directory / marker
                        if directory is not None
                        else git_dir / marker
                    )
                    marker_path.write_text("state\n")
                self.assertEqual(_shared_git_operation_state(repo), expected)

            shared = root / "live/shared_workspace"
            repo = shared / SHARED_GIT_DIRNAME
            ensure_shared_git_repo(repo)
            (repo / ".git/sequencer").mkdir()
            (repo / ".git/sequencer/todo").write_text("exec false\n")
            (repo / "dirty.txt").write_text("must remain on failure\n")
            with self.assertRaisesRegex(RuntimeError, "unrecognized sequencer"):
                clean_shared_git_repo(repo, shared_workspace_dir=shared)
            self.assertEqual((repo / "dirty.txt").read_text(), "must remain on failure\n")

    def test_existing_repo_probe_runs_no_branch_worktree_merge_or_cleanup_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "shared/archive"
            ensure_shared_git_repo(repo)
            real_run_git = main_loop._run_git
            calls: list[tuple[str, ...]] = []

            def recording_run_git(args, cwd, *, check=True):
                calls.append(tuple(args))
                return real_run_git(args, cwd, check=check)

            with patch("main_loop._run_git", side_effect=recording_run_git):
                ensure_shared_git_repo(repo)

            self.assertEqual(calls, [("rev-parse", "--show-toplevel")])
            source = Path(main_loop.__file__).read_text(encoding="utf-8")
            for removed in (
                "create_archive_worktree",
                "finalize_archive_worktree",
                "discard_archive_worktree",
                '"archive_merged"',
                '"archive_committed"',
            ):
                self.assertNotIn(removed, source)

    def test_concurrent_index_lock_failures_are_returned_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "shared/archive"
            ensure_shared_git_repo(repo)
            (repo / "content.txt").write_text("content\n", encoding="utf-8")
            lock_path = repo / ".git/index.lock"
            lock_path.write_text("held externally\n", encoding="utf-8")
            barrier = threading.Barrier(2)
            results: list[dict[str, object]] = []
            results_lock = threading.Lock()

            def run(index: int) -> None:
                barrier.wait()
                result = _run_bash_tool(
                    "git add content.txt",
                    str(repo),
                    worker_state_dir=root / f"state-{index}",
                    timeout_seconds=10,
                    rollout_username=f"rollout-{index}",
                )
                with results_lock:
                    results.append(result)

            threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)

            self.assertEqual(len(results), 2)
            self.assertTrue(all(result["exit_code"] != 0 for result in results))
            self.assertTrue(all("index.lock" in str(result["stderr"]) for result in results))
            self.assertTrue(lock_path.is_file())

    def test_checkout_content_failure_is_returned_without_supervisor_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "shared/archive"
            ensure_shared_git_repo(repo)
            _git(repo, "checkout", "-b", "competing-branch")
            (repo / "WORLD.md").write_text("branch content\n", encoding="utf-8")
            _git(repo, "add", "WORLD.md")
            _git(repo, "commit", "-m", "competing content")
            _git(repo, "checkout", "main")
            (repo / "WORLD.md").write_text("uncommitted local content\n", encoding="utf-8")

            result = _run_bash_tool(
                "git checkout competing-branch",
                str(repo),
                worker_state_dir=root / "state",
                timeout_seconds=10,
                rollout_username="rollout-content-race",
            )

            self.assertNotEqual(result["exit_code"], 0)
            self.assertIn("would be overwritten by checkout", str(result["stderr"]))
            self.assertEqual(_git(repo, "branch", "--show-current").strip(), "main")
            self.assertEqual(
                (repo / "WORLD.md").read_text(encoding="utf-8"),
                "uncommitted local content\n",
            )

    def test_resume_fingerprint_rejects_missing_or_incompatible_partial_state(self) -> None:
        current = {
            "shared_git_enabled": True,
            "shared_git_version": SHARED_GIT_VERSION,
            "shared_git_fingerprint": SHARED_GIT_FINGERPRINT,
        }
        self.assertTrue(
            _shared_git_resume_compatible(current, require_fingerprint=True)
        )
        self.assertFalse(_shared_git_resume_compatible({}, require_fingerprint=True))
        self.assertTrue(_shared_git_resume_compatible({}, require_fingerprint=False))
        self.assertFalse(
            _shared_git_resume_compatible(
                {
                    **current,
                    "shared_git_version": LEGACY_SHARED_GIT_VERSION,
                    "shared_git_fingerprint": LEGACY_SHARED_GIT_FINGERPRINT,
                },
                require_fingerprint=True,
            )
        )


if __name__ == "__main__":
    unittest.main()

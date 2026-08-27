from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import control


TASK_BYTES = (
    b"# Task\n\nProve the Riemann hypothesis.\n\n"
    b"The Riemann hypothesis states that every nontrivial zero of the analytically\n"
    b"continued Riemann zeta function \xce\xb6(s) has real part 1/2.\n"
)


def command(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return command("git", "-C", str(repo), *args, check=check)


class ControlTest(unittest.TestCase):
    def make_study(self, root: Path) -> control.Study:
        (root / "seed").mkdir(parents=True)
        (root / "hooks").mkdir()
        shutil.copy2(Path(control.__file__).parent / "seed/AGENTS.md", root / "seed/AGENTS.md")
        shutil.copy2(Path(control.__file__).parent / "hooks/iteration_boundary.py", root / "hooks/iteration_boundary.py")
        (root / "seed/TASK.md").write_bytes(TASK_BYTES)
        fake = Path(control.__file__).parent / "tests/fake_codex.py"
        fake.chmod(0o755)
        return control.Study(root, str(fake))

    def make_auth(self, root: Path) -> tuple[Path, str]:
        auth_home = root / "auth-home"
        auth_home.mkdir()
        secret = "test-secret-token-9f2e71a8"
        auth = auth_home / "auth.json"
        auth.write_text(json.dumps({"tokens": {"access_token": secret}}), encoding="utf-8")
        auth.chmod(0o600)
        return auth_home, secret

    def initialize(self, root: Path) -> tuple[control.Study, str]:
        study = self.make_study(root / "study")
        auth_home, secret = self.make_auth(root)
        manifest = control.initialize_study(
            study,
            auth_home=auth_home,
        )
        control.verify_layout(study, control.load_json(study.study_state_path))
        self.assertIsNone(manifest["destination"]["head"])
        self.assertTrue(manifest["destination"]["unborn"])
        return study, secret

    def test_init_creates_genuinely_empty_unborn_shared_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            snapshot = control.verify_initial_empty_repository(study.archive)
            self.assertIsNone(snapshot["head"])
            self.assertTrue(snapshot["unborn"])
            self.assertEqual(snapshot["branch"], "refs/heads/main")
            self.assertEqual(snapshot["refs"], [])
            self.assertEqual(snapshot["tracked_file_count"], 0)
            self.assertEqual(snapshot["object_counts"]["count"], 0)
            self.assertEqual(snapshot["object_counts"]["in-pack"], 0)
            self.assertEqual(git(study.archive, "remote").stdout, "")
            self.assertEqual(
                sorted(entry.name for entry in study.archive.iterdir()), [".git"]
            )
            init = control.load_json(study.runtime / "manifests/init.json")
            self.assertEqual(init["archive_seed"], control.empty_repository_pin())
            with self.assertRaisesRegex(control.ControlError, "runtime already exists"):
                control.initialize_study(
                    study,
                    auth_home=Path(raw) / "auth-home",
                )

    def test_stop_and_auto_postcompact_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            control.atomic_json(state / "compaction_counter.json", {"count": 0})
            control.atomic_json(state / "boundary.json", {"target_count": 1})
            environment = os.environ.copy() | {"CONTROL_ROLLOUT_STATE_DIR": str(state)}
            hook = Path(control.__file__).parent / "hooks/iteration_boundary.py"
            stop = command_hook(
                hook,
                {"hook_event_name": "Stop", "session_id": "s", "turn_id": "t"},
                environment,
            )
            self.assertEqual(stop["decision"], "block")
            self.assertEqual(stop["reason"], control.CONTINUATION_INPUT)
            post = command_hook(
                hook,
                {
                    "hook_event_name": "PostCompact",
                    "trigger": "auto",
                    "session_id": "s",
                    "turn_id": "t",
                },
                environment,
            )
            self.assertFalse(post["continue"])
            self.assertEqual(control.read_compaction_count(state), 1)
            events = (state / "hook_events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(events), 2)

    def test_eight_way_fanout_resume_identity_config_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, secret = self.initialize(Path(raw))
            preflight = control.run_preflight(study, real_cli=False)
            self.assertFalse(preflight["tool_controls"]["features.multi_agent"])
            with mock.patch.dict(
                os.environ,
                {"FAKE_PRINT_AUTH": "1", "FAKE_CODEX_DELAY": "0.08"},
                clear=False,
            ):
                first = control.run_iteration(
                    study, resume=False, preflight=True, real_cli=False
                )
            self.assertEqual(first["status"], "complete")
            self.assertEqual(first["compaction_counts_after"], [1] * 8)
            self.assertEqual(len(set(first["session_ids"])), 8)
            self.assertTrue(all(item["prompt"] == control.FRESH_PROMPT for item in first["rollouts"]))
            latest_start = max(item["started_at"] for item in first["rollouts"])
            earliest_end = min(item["ended_at"] for item in first["rollouts"])
            self.assertLess(latest_start, earliest_end)
            shared_paths = {
                event_value(item["stdout"]["path"], "fake.invocation")["shared_realpath"]
                for item in first["rollouts"]
            }
            archive_inodes = {
                (
                    event_value(item["stdout"]["path"], "fake.invocation")["archive_device"],
                    event_value(item["stdout"]["path"], "fake.invocation")["archive_inode"],
                )
                for item in first["rollouts"]
            }
            self.assertEqual(shared_paths, {str(study.shared_workspace.resolve())})
            self.assertEqual(len(archive_inodes), 1)
            for item in first["rollouts"]:
                saved = Path(item["stdout"]["path"]).read_text(encoding="utf-8")
                stderr = Path(item["stderr"]["path"]).read_text(encoding="utf-8")
                self.assertNotIn(secret, saved)
                self.assertNotIn(secret, stderr)
                self.assertGreater(item["stdout"]["redaction_count"], 0)
                self.assertIn("agents.enabled=false", item["command"])
                self.assertEqual(item["command"].count("multi_agent"), 1)
                self.assertEqual(item["command"].count("multi_agent_v2"), 1)
                self.assertFalse(item["stream"]["forbidden_collaboration_tools"])
            self.assertEqual(control.shared_non_archive_entries(study), [])

            second = control.run_iteration(
                study, resume=True, preflight=True, real_cli=False
            )
            self.assertEqual(second["status"], "complete")
            self.assertEqual(second["session_ids"], first["session_ids"])
            self.assertEqual(second["compaction_counts_after"], [2] * 8)
            self.assertTrue(
                all(item["prompt"] == control.CONTINUATION_INPUT for item in second["rollouts"])
            )
            self.assertTrue(all(item["command"][1:3] == ["exec", "resume"] for item in second["rollouts"]))

    def test_incomplete_rollout_fails_barrier_without_cleanup_or_relaunch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            with mock.patch.dict(os.environ, {"FAKE_INCOMPLETE_ROLLOUT": "3"}, clear=False):
                with self.assertRaisesRegex(control.ControlError, "iteration incomplete"):
                    control.run_iteration(
                        study, resume=False, preflight=True, real_cli=False
                    )
            state = control.load_json(study.study_state_path)
            self.assertEqual(state["status"], "blocked_incomplete")
            self.assertEqual(state["completed_iterations"], 0)
            self.assertEqual(state["compaction_counts"][3], 0)
            self.assertEqual(sum(state["compaction_counts"]), 7)
            self.assertTrue((study.shared_workspace / "TASK.md").exists())
            manifest = control.load_json(Path(state["last_iteration_manifest"]))
            self.assertFalse(manifest["barrier_reached"])
            self.assertIsNone(manifest["cleanup"])
            with self.assertRaisesRegex(control.ControlError, "not runnable"):
                control.run_iteration(study, resume=True, preflight=False, real_cli=False)

    def test_cleanup_handles_unborn_head_and_removes_every_dirty_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            repo = study.archive
            git(repo, "config", "user.name", "test")
            git(repo, "config", "user.email", "test@invalid")
            git(repo, "checkout", "--orphan", "preserved")
            (repo / "preserved.txt").write_text("committed\n", encoding="utf-8")
            git(repo, "add", "preserved.txt")
            git(repo, "commit", "-m", "preserved ref")
            preserved_commit = git(repo, "rev-parse", "refs/heads/preserved").stdout
            git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
            (repo / ".git/info/exclude").write_text("*.tmp\n", encoding="utf-8")
            (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
            git(repo, "add", "staged.txt")
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            (repo / "ignored.tmp").write_text("ignored\n", encoding="utf-8")
            nested = repo / "nested"
            command("git", "init", "-b", "main", str(nested))
            (study.shared_workspace / "batch-local").mkdir()
            (study.shared_workspace / "batch-local/file").write_text(
                "local\n", encoding="utf-8"
            )
            before = control.git_snapshot(repo)
            before_refs = control.git_refs_bytes(repo)
            self.assertIsNone(before["head"])
            self.assertTrue(before["unborn"])
            result = control.clean_shared_workspace(
                study,
                control.load_json(study.study_state_path)["archive_identity"],
            )
            after = control.git_snapshot(repo)
            self.assertEqual(result["cleanup_mode"], "unborn-read-tree-empty")
            self.assertIsNone(after["head"])
            self.assertTrue(after["unborn"])
            self.assertEqual(after["branch"], "refs/heads/main")
            self.assertEqual(control.git_refs_bytes(repo), before_refs)
            self.assertEqual(
                git(repo, "rev-parse", "refs/heads/preserved").stdout,
                preserved_commit,
            )
            self.assertEqual(after["tracked_file_count"], 0)
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored").stdout, "")
            self.assertEqual(
                sorted(entry.name for entry in repo.iterdir()), [".git"]
            )
            self.assertEqual(control.shared_non_archive_entries(study), [])

    def test_cleanup_preserves_head_branch_refs_and_deletes_every_dirty_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            repo = study.archive
            git(repo, "config", "user.name", "test")
            git(repo, "config", "user.email", "test@invalid")
            (repo / "WORLD.md").write_text("base\n", encoding="utf-8")
            git(repo, "add", "WORLD.md")
            git(repo, "commit", "-m", "base")
            git(repo, "checkout", "-b", "side")
            (repo / "WORLD.md").write_text("side\n", encoding="utf-8")
            git(repo, "commit", "-am", "side")
            git(repo, "checkout", "main")
            (repo / "WORLD.md").write_text("main\n", encoding="utf-8")
            git(repo, "commit", "-am", "main")
            conflict = git(repo, "merge", "side", check=False)
            self.assertNotEqual(conflict.returncode, 0)
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            (repo / "ignored.tmp").write_text("ignored\n", encoding="utf-8")
            (study.shared_workspace / "batch-local").mkdir()
            (study.shared_workspace / "batch-local/file").write_text("local\n", encoding="utf-8")
            before_head = git(repo, "rev-parse", "HEAD").stdout
            before_branch = git(repo, "symbolic-ref", "HEAD").stdout
            before_refs = control.git_refs_bytes(repo)
            result = control.clean_shared_workspace(
                study,
                control.load_json(study.study_state_path)["archive_identity"],
            )
            self.assertEqual(result["operation_state_cleared"], "merge")
            self.assertEqual(git(repo, "rev-parse", "HEAD").stdout, before_head)
            self.assertEqual(git(repo, "symbolic-ref", "HEAD").stdout, before_branch)
            self.assertEqual(control.git_refs_bytes(repo), before_refs)
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored").stdout, "")
            self.assertEqual(control.shared_non_archive_entries(study), [])
            (repo / ".git/BISECT_START").write_text("HEAD\n", encoding="utf-8")
            with self.assertRaisesRegex(control.ControlError, "bisect"):
                control.clean_shared_workspace(
                    study,
                    control.load_json(study.study_state_path)["archive_identity"],
                )


def command_hook(hook: Path, event: dict[str, object], environment: dict[str, str]) -> dict[str, object]:
    result = subprocess.run(
        [os.fspath(Path(os.sys.executable)), str(hook)],
        input=json.dumps(event).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=True,
    )
    return json.loads(result.stdout)


def event_value(path: str, event_type: str) -> dict[str, object]:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == event_type:
            return event
    raise AssertionError(f"event {event_type} not found in {path}")


if __name__ == "__main__":
    unittest.main()

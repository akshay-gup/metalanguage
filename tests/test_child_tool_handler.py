"""Focused subprocess checks for the standalone child-slot entrypoint."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HANDLER = PROJECT_ROOT / "child_tool_handler.py"


class ChildToolHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workdir = self.root / "work"
        self.workdir.mkdir()
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.context_path = self.root / "context.json"
        self.slots_path = self.root / "slots.json"
        self.slots_dir = self.root / "slots"
        self.progress_path = self.root / "progress.jsonl"
        self.context_path.write_text(json.dumps({
            "workdir": str(self.workdir),
            "spawn_slots_path": str(self.slots_path),
            "spawn_slots_dir": str(self.slots_dir),
            "population_size": 2,
            "task_id": "task",
            "task_index": 3,
            "rollout_index": 0,
            "rollout_username": "rollout-0",
            "instance_uuid": "parent-0",
            "progress_log": str(self.progress_path),
            "generation": 1,
            "seed": 2,
            "shared_archives_root": str(self.archives),
        }), encoding="utf-8")

    def invoke(self, payload: dict[str, object]) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, "-B", str(HANDLER), str(self.context_path)],
            input=json.dumps(payload), text=True, capture_output=True,
            cwd=self.workdir, timeout=5, check=True,
        )
        self.assertFalse(result.stderr, result.stderr)
        return json.loads(result.stdout)

    def prepare_workspace(self) -> Path:
        workspace = self.workdir / "handoff"
        workspace.mkdir()
        (workspace / "AGENTS.md").write_text("# Child\n", encoding="utf-8")
        (workspace / "payload.txt").write_text("inherited\n", encoding="utf-8")
        return workspace

    def test_validates_copies_and_records_exact_child_slot(self) -> None:
        args = {"prompt": "continue", "workspace_dir": "handoff"}
        missing = self.invoke({"tool": "spawn_child", "arguments": args})
        self.assertEqual(missing["error_code"], "invalid_child_workspace")
        self.assertTrue(missing["retryable"])
        self.assertFalse(self.slots_path.exists())

        self.prepare_workspace()
        spawned = self.invoke({"tool": "spawn_child", "arguments": args})
        self.assertTrue(spawned["success"])
        self.assertTrue(spawned["parent_continues"])
        self.assertFalse(spawned["retryable"])
        self.assertEqual(spawned["slot_index"], 0)
        slot = json.loads(self.slots_path.read_text(encoding="utf-8"))["slots"][0]
        manifest = json.loads(Path(slot["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(slot, manifest)
        self.assertEqual(manifest["source_benchmark_item"]["item_id"], "task")
        self.assertEqual((Path(slot["workspace_dir"]) / "payload.txt").read_text(), "inherited\n")
        progress = [json.loads(line) for line in self.progress_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["event"] for record in progress], ["spawn_child_spawned"])
        self.assertEqual(progress[0]["shared_archives_root"], str(self.archives))

        duplicate = self.invoke({"tool": "spawn_child", "arguments": {}})
        self.assertEqual(duplicate["error_code"], "child_already_spawned")
        self.assertFalse(duplicate["retryable"])
        self.assertEqual(len(json.loads(self.slots_path.read_text())["slots"]), 1)

    def test_parallel_requests_keep_one_child_per_rollout(self) -> None:
        self.prepare_workspace()
        payload = {"tool": "spawn_child", "arguments": {"prompt": "continue", "workspace_dir": "handoff"}}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.invoke, [payload, payload]))
        self.assertEqual(sum(bool(result["success"]) for result in results), 1)
        self.assertEqual(sum(result.get("error_code") == "child_already_spawned" for result in results), 1)
        self.assertEqual(len(json.loads(self.slots_path.read_text())["slots"]), 1)

    def test_rejects_escape_and_imports_no_episode_loop(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "AGENTS.md").write_text("# Outside\n", encoding="utf-8")
        (self.workdir / "escape").symlink_to(outside, target_is_directory=True)
        result = self.invoke({"tool": "spawn_child", "arguments": {"prompt": "p", "workspace_dir": "escape"}})
        self.assertEqual(result["error_code"], "invalid_child_workspace")
        unsupported = self.invoke({"tool": "other", "arguments": {}})
        self.assertEqual(unsupported["error_code"], "unsupported_dynamic_tool")
        loaded = subprocess.run(
            [sys.executable, "-B", "-c", "import child_tool_handler, sys; print('main_loop' in sys.modules)"],
            cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=5, check=True,
        )
        self.assertEqual(loaded.stdout.strip(), "False")

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main_loop
from utils.directory_agents_decay import IDENTITY_FILE, claim_policy


class TaskSetupReached(Exception):
    """Stop startup after its real identity checks, before any worker setup."""


class RuntimeBenchmarkStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def start(self, mode="decay", steps=5):
        argv = [
            "main_loop.py", "--benchmark", "open-ended",
            "--worker-backend", "codex", "--model", "gpt-5.6-sol",
            "--runtime-root", str(self.root), "--directory-agents-mode", mode,
        ]
        if steps is not None:
            argv.extend(["--directory-agents-decay-steps", str(steps)])
        with (
            patch("sys.argv", argv),
            patch.object(main_loop, "_resolve_runtime_root", return_value=self.root),
            patch.object(main_loop, "resolve_open_ended_task", side_effect=TaskSetupReached),
            patch.object(main_loop, "resolve_codex_runner_bin", side_effect=AssertionError("worker setup must not run")),
        ):
            main_loop._run_main([])

    def initialize_metadata(self):
        main_loop._claim_runtime_archive_identity(self.root)
        claim_policy(self.root, "decay", 5, was_empty=True)

    def test_fresh_decay_initialization_reaches_task_setup(self):
        # Exercise _run_main's actual archive -> policy -> benchmark ordering.
        with self.assertRaises(TaskSetupReached):
            self.start()
        self.assertIsNone(main_loop._runtime_benchmark(self.root))
        self.assertEqual(
            json.loads((self.root / IDENTITY_FILE).read_text()),
            {"schema": 1, "mode": "decay", "steps": 5},
        )
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {main_loop.RUNTIME_ARCHIVE_IDENTITY_FILENAME, IDENTITY_FILE},
        )

    def test_fresh_cumulative_initialization_reaches_task_setup(self):
        with self.assertRaises(TaskSetupReached):
            self.start("cumulative", None)
        self.assertIsNone(main_loop._runtime_benchmark(self.root))
        self.assertEqual(
            {path.name for path in self.root.iterdir()},
            {main_loop.RUNTIME_ARCHIVE_IDENTITY_FILENAME},
        )

    def test_policy_metadata_does_not_hide_legacy_data(self):
        self.initialize_metadata()
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "runs.jsonl").write_text('{"benchmark":"supergpqa"}\n')
        self.assertEqual(main_loop._runtime_benchmark(self.root), "supergpqa")
        with self.assertRaisesRegex(SystemExit, "belongs to benchmark supergpqa"):
            self.start()
        # Legacy detection must also retain unknown data, not just known logs.
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory)
            (other / "research.json").write_text("{}")
            self.assertEqual(main_loop._runtime_benchmark(other), "supergpqa")

    def test_explicit_benchmark_identity_remains_authoritative(self):
        self.initialize_metadata()
        identity = self.root / main_loop.RUNTIME_BENCHMARK_IDENTITY_FILENAME
        for benchmark in ("supergpqa", "arc-agi"):
            with self.subTest(benchmark=benchmark):
                identity.write_text(json.dumps({"benchmark": benchmark}))
                with self.assertRaisesRegex(SystemExit, "belongs to benchmark " + benchmark):
                    self.start()
        identity.write_text(json.dumps({"benchmark": "open-ended"}))
        with self.assertRaises(TaskSetupReached):
            self.start()

    def test_invalid_benchmark_identity_is_not_treated_as_fresh(self):
        self.initialize_metadata()
        identity = self.root / main_loop.RUNTIME_BENCHMARK_IDENTITY_FILENAME
        for content in ("{", "[]", '{"benchmark":"unknown"}'):
            with self.subTest(content=content):
                identity.write_text(content)
                with self.assertRaisesRegex(RuntimeError, "benchmark identity"):
                    self.start()

    def test_archive_identity_guard_still_rejects_existing_or_incompatible_roots(self):
        (self.root / "research.json").write_text("{}")
        with self.assertRaisesRegex(SystemExit, "predates.*shared-archive"):
            self.start("cumulative", None)
        identity = self.root / main_loop.RUNTIME_ARCHIVE_IDENTITY_FILENAME
        identity.write_text("{}")
        with self.assertRaisesRegex(SystemExit, "archive identity is incompatible"):
            self.start("cumulative", None)

    def test_decay_policy_guards_still_reject_migration_and_changes(self):
        main_loop._claim_runtime_archive_identity(self.root)
        with self.assertRaisesRegex(ValueError, "requires a fresh runtime root"):
            self.start()
        claim_policy(self.root, "decay", 5, was_empty=True)
        for mode, steps in (("decay", 8), ("cumulative", None)):
            with self.subTest(mode=mode, steps=steps):
                with self.assertRaisesRegex(ValueError, "policy changed"):
                    self.start(mode, steps)
        (self.root / IDENTITY_FILE).write_text("{")
        with self.assertRaises(json.JSONDecodeError):
            self.start()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.directory_agents_decay import IDENTITY_FILE, claim_policy, validate_policy
from utils.directory_agents_hook import resolve_decay_access


class DecayPolicyTests(unittest.TestCase):
    def test_requires_explicit_positive_integer_and_codex_only(self):
        for value in (None, 0, -1, True, 1.5, 2**64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_policy("decay", value, {"codex"})
        for backends in ({"opencode"}, {"openrouter"}, {"codex", "opencode"}):
            with self.subTest(backends=backends), self.assertRaises(ValueError):
                validate_policy("decay", 2, backends)
        validate_policy("decay", 1, {"codex"})
        validate_policy("cumulative", None, {"opencode", "codex"})
        with self.assertRaises(ValueError):
            validate_policy("cumulative", 1, {"codex"})

    def test_runtime_identity_prevents_migration_and_changed_k(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            claim_policy(root, "cumulative", None, was_empty=False)
            self.assertFalse((root / IDENTITY_FILE).exists())
            with self.assertRaises(ValueError):
                claim_policy(root, "decay", 2, was_empty=False)
            claim_policy(root, "decay", 2, was_empty=True)
            claim_policy(root, "decay", 2, was_empty=False)
            for mode, steps in (("cumulative", None), ("decay", 1)):
                with self.subTest(mode=mode, steps=steps), self.assertRaises(ValueError):
                    claim_policy(root, mode, steps, was_empty=False)
            (root / IDENTITY_FILE).write_text("{", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                claim_policy(root, "decay", 2, was_empty=False)


class DecayResolverTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.a, self.b = self.root / "a", self.root / "b"
        for directory, text in ((self.root, "root fixed"), (self.a, "same"), (self.b, "same")):
            directory.mkdir(exist_ok=True)
            (directory / "AGENTS.md").write_text(text, encoding="utf-8")
        self.context = {"workdir": str(self.root)}

    def resolve(self, command="pwd", workdir=None, event="PreToolUse"):
        args = {"command": command}
        if workdir is not None:
            args["workdir"] = str(workdir)
        return resolve_decay_access(self.context, {
            "hook_event_name": event, "tool_name": "Bash",
            "tool_input": args, "cwd": str(self.root),
        })

    def test_exact_union_root_excluded_and_no_historical_dedup(self):
        result = self.resolve("cd a; cd ../b")
        self.assertEqual([guide["path"] for guide in result["guides"]],
                         [str(self.a / "AGENTS.md"), str(self.b / "AGENTS.md")])
        self.assertEqual(result, self.resolve("cd a; cd ../b"))
        self.assertEqual(self.resolve()["guides"], [])
        self.assertEqual(self.resolve()["observations"][0]["status"], "fixed_root")
        (self.root / "AGENTS.md").write_text("root revised", encoding="utf-8")
        self.assertEqual(self.resolve()["guides"], [])

    def test_explicit_start_scope_and_partial_unknown(self):
        self.assertEqual([g["path"] for g in self.resolve('cd "$UNKNOWN"', self.a)["guides"]],
                         [str(self.a / "AGENTS.md")])
        self.assertEqual(self.resolve('cd "$UNKNOWN"')["guides"], [])
        result = resolve_decay_access(self.context, {"tool_name": "unknown", "tool_input": {}})
        self.assertEqual(result["observations"], [{"status": "unknown"}])

    def test_missing_empty_unreadable_and_symlink_do_not_renew(self):
        agents = self.a / "AGENTS.md"
        agents.unlink()
        self.assertEqual(self.resolve(workdir=self.a)["observations"][0]["status"], "absent")
        agents.write_text(" \n", encoding="utf-8")
        self.assertEqual(self.resolve(workdir=self.a)["observations"][0]["status"], "empty")
        agents.write_bytes(b"\xff")
        self.assertEqual(self.resolve(workdir=self.a)["observations"][0]["status"], "unreadable")
        agents.unlink()
        agents.symlink_to(self.b / "AGENTS.md")
        result = self.resolve(workdir=self.a)
        self.assertEqual(result["guides"], [])
        self.assertEqual(result["observations"][0]["status"], "excluded")

    def test_read_error_and_postfallback_revision(self):
        with patch("utils.directory_agents_hook.os.open", side_effect=PermissionError):
            self.assertEqual(self.resolve(workdir=self.a)["guides"], [])
        before = self.resolve(workdir=self.a)["guides"][0]
        (self.a / "AGENTS.md").write_text("new version", encoding="utf-8")
        after = self.resolve(workdir=self.a, event="PostToolUse")["guides"][0]
        self.assertNotEqual(before["digest"], after["digest"])
        self.assertEqual(before["path"], after["path"])
        self.assertEqual(self.resolve("cd new-dir")["guides"], [])
        created = self.root / "new-dir"
        created.mkdir()
        (created / "AGENTS.md").write_text("new scope", encoding="utf-8")
        self.assertEqual(len(self.resolve("cd new-dir", event="PostToolUse")["guides"]), 1)

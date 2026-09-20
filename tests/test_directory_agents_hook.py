from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main_loop import run_worker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK = PROJECT_ROOT / "utils/directory_agents_hook.py"


class DirectoryAgentsHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        temp_root = Path(self.temp.name)
        self.managed = temp_root / "managed"
        self.archives = self.managed / "archives"
        self.project = self.archives / "project"
        self.shared = temp_root / "shared"
        self.control = temp_root / "control"
        for directory in (self.project, self.shared, self.control):
            directory.mkdir(parents=True)
        (self.managed / "AGENTS.md").write_text("root context\n", encoding="utf-8")
        (self.archives / "AGENTS.md").write_text("archives context\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("project context\n", encoding="utf-8")
        self.context_path = self.control / "continuation_context.json"
        self.context_path.write_text(
            json.dumps(
                {
                    "workdir": str(self.managed),
                    "shared_archives_root": str(self.archives),
                    "shared_workspace_dir": str(self.shared),
                }
            ),
            encoding="utf-8",
        )
        initial = self._invoke({"hook_event_name": "UserPromptSubmit"})
        self.assertIn("root context", initial)

    def _invoke_response(self, payload: dict[str, object]) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(HOOK), str(self.context_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        if not completed.stdout.strip():
            return {}
        return json.loads(completed.stdout)

    def _invoke(self, payload: dict[str, object]) -> str:
        response = self._invoke_response(payload)
        if not response:
            return ""
        return str(response["hookSpecificOutput"]["additionalContext"])

    def _bash(self, command: str, **tool_input: str) -> str:
        return self._invoke(
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command, **tool_input},
            }
        )

    def test_literal_cd_activates_exact_directory_and_deduplicates(self) -> None:
        context = self._bash("cd archives/project && printf work")
        self.assertIn("project context", context)
        self.assertNotIn("archives context", context)
        self.assertEqual(self._bash("cd archives/project && printf again"), "")
        (self.project / "AGENTS.md").write_text(
            "revised project context\n",
            encoding="utf-8",
        )
        self.assertIn(
            "revised project context",
            self._bash("cd archives/project && printf revised"),
        )

    def test_quoted_path_and_pushd_are_supported(self) -> None:
        quoted = self.archives / "quoted project"
        quoted.mkdir()
        (quoted / "AGENTS.md").write_text("quoted context\n", encoding="utf-8")

        context = self._bash("pushd 'archives/quoted project' >/dev/null && pwd")

        self.assertIn("quoted context", context)

    def test_multiple_and_parent_transitions_resolve_sequentially(self) -> None:
        context = self._bash("cd archives; cd project; cd ..")

        self.assertEqual(context.count("archives context"), 1)
        self.assertEqual(context.count("project context"), 1)

    def test_parent_transition_uses_explicit_workdir_as_its_start(self) -> None:
        context = self._bash("cd .. && pwd", workdir=str(self.project))

        self.assertIn("project context", context)
        self.assertIn("archives context", context)

    def test_absolute_managed_path_activates(self) -> None:
        context = self._bash(f"cd {self.project} && pwd")

        self.assertIn("project context", context)

    def test_compound_command_activates_literal_transition(self) -> None:
        context = self._bash("cd archives/project && printf end")

        self.assertIn("project context", context)
        self.assertEqual(
            self._bash("python3 -c 'raise SystemExit(1)' && cd archives/project"),
            "",
        )

    def test_failed_change_does_not_activate_later_and_branch(self) -> None:
        context = self._bash("cd archives/missing && cd archives/project")

        self.assertEqual(context, "")
        self.assertEqual(self._bash("false && cd archives/project"), "")
        self.assertEqual(
            self._bash('cd "$PROJECT" || cd archives/project'),
            "",
        )
        self.assertEqual(self._bash("cd archives/project &&"), "")
        self.assertEqual(self._bash("cd archives/project >"), "")
        not_a_directory = self.archives / "not-a-directory"
        not_a_directory.write_text("file\n", encoding="utf-8")
        self.assertEqual(self._bash("cd archives/not-a-directory"), "")

    def test_outside_root_path_does_not_activate(self) -> None:
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "AGENTS.md").write_text("outside context\n", encoding="utf-8")

        context = self._bash(f"cd {outside} && pwd")

        self.assertEqual(context, "")
        (self.archives / "outside-link").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self._bash("cd archives/outside-link && pwd"), "")

    def test_quoted_and_commented_fake_cd_text_does_not_activate(self) -> None:
        context = self._bash(
            "printf '%s' 'cd archives/project' # cd archives/project\n"
            'printf "%s" "still not: cd archives/project"'
        )

        self.assertEqual(context, "")

    def test_heredoc_cd_text_does_not_activate(self) -> None:
        context = self._bash(
            "cat <<'EOF'\n"
            "cd archives/project\n"
            "EOF\n"
            "printf done\n"
        )

        self.assertEqual(context, "")

    def test_empty_exact_child_does_not_fall_back_to_parent(self) -> None:
        empty = self.archives / "empty"
        empty.mkdir()
        (empty / "AGENTS.md").write_text("  \n", encoding="utf-8")

        context = self._bash("cd archives/empty && pwd")

        self.assertEqual(context, "")

    def test_git_c_resolves_quoted_repeated_and_relative_operands_in_order(self) -> None:
        git_root = self.archives / "git root"
        git_sub = git_root / "sub"
        git_root.mkdir()
        git_sub.mkdir()
        (git_root / "AGENTS.md").write_text("git root context\n", encoding="utf-8")
        (git_sub / "AGENTS.md").write_text("git sub context\n", encoding="utf-8")

        context = self._bash("git -C archives -C 'git root' -C sub status")

        self.assertIn("archives context", context)
        self.assertIn("git root context", context)
        self.assertIn("git sub context", context)

    def test_multiple_git_c_commands_and_failed_git_still_activate(self) -> None:
        first = self.archives / "git-first"
        second = self.archives / "git-second"
        for directory, content in (
            (first, "git first context\n"),
            (second, "git second context\n"),
        ):
            directory.mkdir()
            (directory / "AGENTS.md").write_text(content, encoding="utf-8")

        context = self._bash(
            "git -C archives/git-first definitely-not-a-command; "
            "git -C archives/git-second status"
        )

        self.assertIn("git first context", context)
        self.assertIn("git second context", context)

    def test_git_c_honors_cd_relative_base_and_double_dash(self) -> None:
        relative = self.archives / "relative-git"
        absolute = self.archives / "absolute-git"
        ignored = self.archives / "after-double-dash"
        for directory, content in (
            (relative, "relative git context\n"),
            (absolute, "absolute git context\n"),
            (ignored, "ignored git context\n"),
        ):
            directory.mkdir()
            (directory / "AGENTS.md").write_text(content, encoding="utf-8")

        context = self._bash("cd archives; git -C relative-git status")
        self.assertIn("relative git context", context)
        self.assertIn(
            "absolute git context",
            self._bash(f"git -C {absolute} status"),
        )
        self.assertEqual(self._bash("git -- -C archives/after-double-dash status"), "")

    def test_git_c_rejects_dynamic_malformed_and_outside_operands(self) -> None:
        dynamic = self.archives / "dynamic-git"
        dynamic.mkdir()
        (dynamic / "AGENTS.md").write_text("dynamic git context\n", encoding="utf-8")
        outside = Path(self.temp.name) / "outside-git"
        outside.mkdir()
        (outside / "AGENTS.md").write_text("outside git context\n", encoding="utf-8")

        self.assertEqual(self._bash('git -C "$repo" status'), "")
        self.assertEqual(self._bash("git -C"), "")
        self.assertEqual(self._bash(f"git -C {outside} status"), "")
        self.assertEqual(
            self._bash('git -C archives -C "$repo" status'),
            "",
        )


class OpenRouterDirectoryAgentsTests(unittest.TestCase):
    def test_literal_transition_is_context_only_and_preserves_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workdir = root / "work"
            archives = workdir / "archives"
            project = archives / "project"
            seed_output = workdir / "seed_output"
            shared = workdir / "shared_workspace"
            state = root / "state"
            for directory in (project, seed_output, shared, state):
                directory.mkdir(parents=True)
            (project / "AGENTS.md").write_text(
                "openrouter project context\n",
                encoding="utf-8",
            )

            captured_inputs: list[list[dict[str, object]]] = []
            responses = iter(
                [
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "id": "item-1",
                                "call_id": "call-1",
                                "name": "run_bash",
                                "arguments": json.dumps(
                                    {
                                        "command": (
                                            "cd archives/project\n"
                                            "printf visible-out\n"
                                            "printf visible-err >&2\n"
                                            "false"
                                        )
                                    }
                                ),
                            }
                        ],
                    },
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "function_call",
                                "id": "item-2",
                                "call_id": "call-2",
                                "name": "run_bash",
                                "arguments": json.dumps({"command": "pwd -P"}),
                            }
                        ],
                    },
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "done"}],
                            }
                        ],
                    },
                ]
            )

            def fake_call(**kwargs: object) -> dict[str, object]:
                self.assertEqual(kwargs["instructions"], "Read AGENTS.md.")
                captured_inputs.append(
                    json.loads(json.dumps(kwargs["input_items"]))
                )
                return next(responses)

            benchmark_driver = SimpleNamespace(handle_tool=lambda *_args: None)
            rollout_benchmark = SimpleNamespace(model_metadata={"tools": []})
            with patch("main_loop.call_openrouter_with_tools", side_effect=fake_call):
                result = run_worker(
                    api_key="test",
                    model="test/model",
                    workdir=workdir,
                    seed_output_dir=seed_output,
                    shared_archives_root=archives,
                    shared_workspace_dir=shared,
                    worker_state_dir=state,
                    shared_workspace_write_log=root / "shared-writes.jsonl",
                    task_index=0,
                    task_id="test",
                    rollout_index=0,
                    rollout_username="test-user",
                    timeout_seconds=10,
                    bash_timeout_seconds=5,
                    openrouter_max_retries=0,
                    continuation_context={
                        "workdir": str(workdir),
                        "shared_archives_root": str(archives),
                        "shared_workspace_dir": str(shared),
                    },
                    benchmark_driver=benchmark_driver,
                    rollout_benchmark=rollout_benchmark,
                    initial_user_text="Begin.",
                )

            self.assertEqual(result.final_text, "done")
            self.assertEqual(
                captured_inputs[0][0]["content"][0]["text"],
                "Begin.",
            )
            developer_messages = [
                item
                for item in captured_inputs[1]
                if item.get("role") == "developer"
            ]
            self.assertEqual(len(developer_messages), 1)
            self.assertIn(
                "openrouter project context",
                developer_messages[0]["content"][0]["text"],
            )
            first_output = next(
                item
                for item in captured_inputs[1]
                if item.get("type") == "function_call_output"
            )
            first_result = json.loads(first_output["output"])
            self.assertEqual(first_result["exit_code"], 1)
            self.assertEqual(first_result["stdout"], "visible-out")
            self.assertEqual(first_result["stderr"], "visible-err")
            self.assertNotIn("metalanguage", first_output["output"].lower())

            second_outputs = [
                item
                for item in captured_inputs[2]
                if item.get("type") == "function_call_output"
            ]
            second_result = json.loads(second_outputs[-1]["output"])
            self.assertEqual(second_result["exit_code"], 0)
            self.assertEqual(second_result["stdout"], f"{workdir.resolve()}\n")


if __name__ == "__main__":
    unittest.main()

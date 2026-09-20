from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main_loop import run_codex_worker, run_opencode_worker, run_worker
from utils.directory_agents_hook import (
    initial_context_activation,
    pre_tool_context_gate,
)


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
        initial = initial_context_activation(
            json.loads(self.context_path.read_text(encoding="utf-8")),
            self.control / "directory_agents_seen",
        )
        self.assertIn("root context", initial.additional_context)

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

    def _pre_response(
        self,
        command: str,
        **tool_input: str,
    ) -> dict[str, object]:
        return self._invoke_response(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command, **tool_input},
            }
        )

    def _pre(self, command: str, **tool_input: str) -> str:
        response = self._pre_response(command, **tool_input)
        if not response:
            return ""
        return str(response["hookSpecificOutput"]["additionalContext"])

    def test_pre_tool_first_unseen_defers_then_repeat_executes(self) -> None:
        response = self._pre_response("cd archives/project && printf work")

        self.assertEqual(
            response["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertEqual(
            response["hookSpecificOutput"]["permissionDecisionReason"],
            "Local context activated; tool was not executed.",
        )
        self.assertIn(
            "<CONTEXT>\nproject context\n</CONTEXT>",
            response["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual(self._pre("cd archives/project && printf work"), "")
        records = (
            (self.control / "directory_agents_seen")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(records[-1].split("\t")[2], "pre_tool_gate")

    def test_user_prompt_hook_is_disabled_after_direct_initial_delivery(self) -> None:
        self.assertEqual(self._invoke({"hook_event_name": "UserPromptSubmit"}), "")

    def test_pre_tool_changed_digest_defers_again(self) -> None:
        self.assertIn("project context", self._pre("cd archives/project"))
        (self.project / "AGENTS.md").write_text("revised context\n", encoding="utf-8")

        self.assertIn("revised context", self._pre("cd archives/project"))
        self.assertEqual(self._pre("cd archives/project"), "")

    def test_root_is_already_seen_before_first_tool(self) -> None:
        self.assertEqual(self._pre("pwd"), "")

    def test_pre_tool_multiple_contexts_produce_one_deferral(self) -> None:
        response = self._pre_response("cd archives; cd project; pwd")
        context = str(response["hookSpecificOutput"]["additionalContext"])

        self.assertEqual(response["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(context.count("<CONTEXT>"), 2)
        self.assertIn("archives context", context)
        self.assertIn("project context", context)
        self.assertEqual(self._pre("cd archives; cd project; pwd"), "")

    def test_pre_tool_explicit_workdir_and_git_c_are_eligible(self) -> None:
        explicit = self._invoke_response(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "read_file",
                "tool_input": {"workdir": str(self.project)},
            }
        )
        self.assertIn(
            "project context",
            explicit["hookSpecificOutput"]["additionalContext"],
        )
        (self.archives / "AGENTS.md").write_text("git revision\n", encoding="utf-8")
        git_response = self._pre_response("git -C archives status")
        self.assertIn(
            "git revision",
            git_response["hookSpecificOutput"]["additionalContext"],
        )

    def test_pre_tool_static_branches_gate_but_unknown_and_dynamic_do_not(self) -> None:
        self.assertIn("project context", self._pre("true && cd archives/project"))
        (self.project / "AGENTS.md").write_text("branch revision\n", encoding="utf-8")
        self.assertEqual(self._pre("printf unknown && cd archives/project"), "")
        self.assertEqual(self._pre('cd "$PROJECT"'), "")
        self.assertEqual(
            self._pre('cd "$PROJECT" || cd archives/project'),
            "",
        )
        self.assertIn(
            "branch revision",
            self._pre("printf unknown; cd archives/project"),
        )

    def test_pre_and_post_share_deduplication_state(self) -> None:
        self.assertIn("project context", self._pre("cd archives/project"))
        self.assertEqual(self._bash("cd archives/project"), "")
        (self.project / "AGENTS.md").write_text("post revision\n", encoding="utf-8")
        self.assertIn("post revision", self._bash("cd archives/project"))
        self.assertEqual(self._pre("cd archives/project"), "")
        records = (
            (self.control / "directory_agents_seen")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(records[-1].split("\t")[2], "post_tool_fallback")

    def test_post_tool_fallback_can_activate_a_newly_created_scope(self) -> None:
        created = self.archives / "created-later"
        self.assertEqual(self._pre("cd archives/created-later"), "")
        created.mkdir()
        (created / "AGENTS.md").write_text("created context\n", encoding="utf-8")

        self.assertIn("created context", self._bash("cd archives/created-later"))

    def test_pre_tool_ignores_missing_empty_unsafe_and_outside_agents(self) -> None:
        missing = self.archives / "missing-agents"
        empty = self.archives / "empty-agents"
        unsafe = self.archives / "unsafe-agents"
        outside = Path(self.temp.name) / "outside-pre"
        for directory in (missing, empty, unsafe, outside):
            directory.mkdir()
        (empty / "AGENTS.md").write_text(" \n", encoding="utf-8")
        target = outside / "target.md"
        target.write_text("outside context\n", encoding="utf-8")
        (unsafe / "AGENTS.md").symlink_to(target)
        (outside / "AGENTS.md").write_text("outside context\n", encoding="utf-8")

        self.assertEqual(self._pre("cd archives/missing-agents"), "")
        self.assertEqual(self._pre("cd archives/empty-agents"), "")
        self.assertEqual(self._pre("cd archives/unsafe-agents"), "")
        self.assertEqual(self._pre(f"cd {outside}"), "")

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


class InitialDirectoryContextBackendTests(unittest.TestCase):
    def test_each_rollout_workspace_kind_claims_its_actual_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for lifecycle in ("fresh-bootstrap", "inherited-child", "bootstrap-reinitialized"):
                with self.subTest(lifecycle=lifecycle):
                    workdir = root / lifecycle / "work"
                    state_path = root / lifecycle / "control" / "directory_agents_seen"
                    workdir.mkdir(parents=True)
                    content = f"{lifecycle} root\n"
                    (workdir / "AGENTS.md").write_text(content, encoding="utf-8")
                    context = {"workdir": str(workdir)}

                    initial = initial_context_activation(context, state_path)

                    self.assertEqual(
                        initial.additional_context,
                        f"<CONTEXT>\n{content.rstrip()}\n</CONTEXT>",
                    )
                    self.assertEqual(initial.activation, "initial")
                    self.assertFalse(
                        pre_tool_context_gate(
                            context,
                            {
                                "hook_event_name": "PreToolUse",
                                "tool_name": "bash",
                                "tool_input": {"command": "pwd"},
                                "cwd": str(workdir),
                            },
                            state_path,
                        ).deferred
                    )
                    (workdir / "AGENTS.md").write_text(
                        f"{lifecycle} revised\n",
                        encoding="utf-8",
                    )
                    self.assertTrue(
                        pre_tool_context_gate(
                            context,
                            {
                                "hook_event_name": "PreToolUse",
                                "tool_name": "bash",
                                "tool_input": {"command": "pwd"},
                                "cwd": str(workdir),
                            },
                            state_path,
                        ).deferred
                    )
                    self.assertFalse(
                        pre_tool_context_gate(
                            context,
                            {
                                "hook_event_name": "PreToolUse",
                                "tool_name": "bash",
                                "tool_input": {"command": "pwd"},
                                "cwd": str(workdir),
                            },
                            state_path,
                        ).deferred
                    )

    def test_codex_initial_context_uses_developer_request_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = {
                name: root / name
                for name in ("work", "control", "state", "codex", "seed", "archives", "shared")
            }
            for path in paths.values():
                path.mkdir()
            (paths["work"] / "AGENTS.md").write_text("codex root\n", encoding="utf-8")
            context = {
                "workdir": str(paths["work"]),
                "shared_archives_root": str(paths["archives"]),
                "shared_workspace_dir": str(paths["shared"]),
            }
            context_path = paths["control"] / "continuation_context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            events: list[tuple[str, dict[str, object]]] = []
            completed = {
                "final_text": "done",
                "status": "completed",
                "stop_reason": "final_message",
                "error_code": None,
                "error_message": None,
            }

            with patch("main_loop.run_codex_rollout", return_value=completed) as rollout:
                run_codex_worker(
                    runner_bin=root / "runner",
                    model="gpt-5.6-sol",
                    workdir=paths["work"],
                    control_dir=paths["control"],
                    worker_state_dir=paths["state"],
                    codex_home=paths["codex"],
                    seed_output_dir=paths["seed"],
                    shared_archives_root=paths["archives"],
                    shared_workspace_dir=paths["shared"],
                    rollout_username="rollout",
                    timeout_seconds=10,
                    sandbox_mode="workspace-write",
                    initial_user_text="Begin.",
                    continuation_context=context,
                    continuation_context_path=context_path,
                    progress_callback=lambda event, **fields: events.append((event, fields)),
                )

            kwargs = rollout.call_args.kwargs
            self.assertEqual(kwargs["initial_user_text"], "Begin.")
            self.assertEqual(
                kwargs["initial_developer_context"],
                "<CONTEXT>\ncodex root\n</CONTEXT>",
            )
            self.assertEqual(events[0][1]["activation"], "initial")
            record = context_path.with_name("directory_agents_seen").read_text(encoding="utf-8")
            self.assertEqual(record.splitlines()[0].split("\t")[2], "initial")
            self.assertFalse(
                pre_tool_context_gate(
                    context,
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "exec_command",
                        "tool_input": {"command": "pwd"},
                        "cwd": str(paths["work"]),
                    },
                    context_path.with_name("directory_agents_seen"),
                ).deferred
            )

    def test_opencode_initial_context_uses_system_request_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = {name: root / name for name in ("work", "control", "state")}
            for path in paths.values():
                path.mkdir()
            (paths["work"] / "AGENTS.md").write_text("opencode root\n", encoding="utf-8")
            context = {"workdir": str(paths["work"])}
            context_path = paths["control"] / "continuation_context.json"
            context_path.write_text(json.dumps(context), encoding="utf-8")
            completed = {
                "final_text": "done",
                "status": "completed",
                "stop_reason": "final_message",
                "error_code": None,
                "error_message": None,
                "error_http_status": None,
                "error_retryable": None,
            }

            with patch("main_loop.run_opencode_rollout", return_value=completed) as rollout:
                run_opencode_worker(
                    worker_script=root / "worker.ts",
                    bun_bin=root / "bun",
                    opencode_bin=root / "opencode",
                    model="openrouter/gpt-5.6-sol",
                    workdir=paths["work"],
                    control_dir=paths["control"],
                    worker_state_dir=paths["state"],
                    timeout_seconds=10,
                    initial_user_text="Begin.",
                    system_instructions=".",
                    continuation_context=context,
                    continuation_context_path=context_path,
                )

            kwargs = rollout.call_args.kwargs
            self.assertEqual(kwargs["initial_user_text"], "Begin.")
            self.assertEqual(kwargs["system_instructions"], ".")
            self.assertEqual(
                kwargs["initial_system_context"],
                "<CONTEXT>\nopencode root\n</CONTEXT>",
            )
            record = context_path.with_name("directory_agents_seen").read_text(encoding="utf-8")
            self.assertEqual(record.splitlines()[0].split("\t")[2], "initial")
            self.assertFalse(
                pre_tool_context_gate(
                    context,
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "bash",
                        "tool_input": {"command": "pwd"},
                        "cwd": str(paths["work"]),
                    },
                    context_path.with_name("directory_agents_seen"),
                ).deferred
            )


class OpenRouterDirectoryAgentsTests(unittest.TestCase):
    def test_pre_gate_has_no_side_effect_and_repeat_preserves_tool_result(self) -> None:
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
            side_effect = project / "side-effect.txt"

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
                                            "printf executed > side-effect.txt\n"
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
                                "arguments": json.dumps(
                                    {
                                        "command": (
                                            "cd archives/project\n"
                                            "printf executed > side-effect.txt\n"
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
                                "id": "item-3",
                                "call_id": "call-3",
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
                if len(captured_inputs) == 2:
                    self.assertFalse(side_effect.exists())
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
            self.assertEqual(first_result["status"], "deferred")
            self.assertEqual(
                first_result["message"],
                "Local context activated; tool was not executed.",
            )
            self.assertIs(first_result["tool_executed"], False)

            repeated_output = next(
                item
                for item in captured_inputs[2]
                if item.get("type") == "function_call_output"
                and item.get("call_id") == "call-2"
            )
            repeated_result = json.loads(repeated_output["output"])
            self.assertEqual(repeated_result["exit_code"], 1)
            self.assertEqual(repeated_result["stdout"], "visible-out")
            self.assertEqual(repeated_result["stderr"], "visible-err")
            self.assertTrue(side_effect.is_file())

            second_outputs = [
                item
                for item in captured_inputs[3]
                if item.get("type") == "function_call_output"
            ]
            second_result = json.loads(second_outputs[-1]["output"])
            self.assertEqual(second_result["exit_code"], 0)
            self.assertEqual(second_result["stdout"], f"{workdir.resolve()}\n")

    def test_root_context_is_injected_and_marked_before_first_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workdir = root / "work"
            archives = workdir / "archives"
            seed_output = workdir / "seed_output"
            shared = workdir / "shared_workspace"
            state = root / "state"
            for directory in (workdir, archives, seed_output, shared, state):
                directory.mkdir(parents=True, exist_ok=True)
            (workdir / "AGENTS.md").write_text("root managed context\n", encoding="utf-8")

            captured: list[dict[str, object]] = []

            def fake_call(**kwargs: object) -> dict[str, object]:
                captured.extend(json.loads(json.dumps(kwargs["input_items"])))
                return {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "done"}],
                        }
                    ],
                }

            with patch("main_loop.call_openrouter_with_tools", side_effect=fake_call):
                run_worker(
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
                    benchmark_driver=SimpleNamespace(handle_tool=lambda *_args: None),
                    rollout_benchmark=SimpleNamespace(model_metadata={"tools": []}),
                    initial_user_text="Begin.",
                )

            self.assertEqual(captured[0]["role"], "developer")
            self.assertIn("root managed context", captured[0]["content"][0]["text"])
            self.assertEqual(captured[1]["role"], "user")
            record = (
                (state / "directory_agents_seen")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertEqual(record.split("\t")[2], "initial")


if __name__ == "__main__":
    unittest.main()

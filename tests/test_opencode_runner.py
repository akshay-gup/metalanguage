from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.opencode_runner import (
    _handle_runner_line,
    _terminate_process_group,
    opencode_worker_script_path,
    resolve_bun_bin,
    run_opencode_rollout,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_OPENCODE = PROJECT_ROOT / "tests/fixtures/fake_opencode.py"


class Buffer:
    def __init__(self) -> None:
        self.value = ""

    def write(self, value: str) -> None:
        self.value += value

    def flush(self) -> None:
        return


class OpenCodeRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker_script = opencode_worker_script_path()
        self.bun_bin = resolve_bun_bin(None)

    def _fake_cli(self, root: Path) -> Path:
        target = root / "opencode"
        shutil.copyfile(FAKE_OPENCODE, target)
        target.chmod(0o755)
        return target

    def _assert_pid_gone(self, pid: int) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        self.fail(f"process {pid} survived cleanup")

    def _run(
        self,
        root: Path,
        *,
        prompt: str = "ordinary prompt",
        mcp: dict[str, object] | None = None,
        sensitive: tuple[tuple[str, str], ...] = (),
        timeout: int = 5,
    ) -> dict[str, object]:
        workdir = root / "workdir"
        workdir.mkdir()
        return run_opencode_rollout(
            worker_script=self.worker_script,
            bun_bin=self.bun_bin,
            opencode_bin=self._fake_cli(root),
            model="fixture/model",
            workdir=workdir,
            control_dir=root / "control",
            worker_state_dir=root / "state",
            timeout_seconds=timeout,
            initial_user_text=prompt,
            system_instructions="exact system instruction",
            continuation_context_path=root / "continuation.json",
            benchmark_mcp_servers=mcp,
            sensitive_mcp_tools=sensitive,
            allowed_versions=("1.18.18",),
            startup_timeout_seconds=2,
        )

    def test_vertical_slice_exact_prompt_state_isolation_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._run(root)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "fixture final")
            self.assertEqual(result["runtime_version"], "1.18.18")
            self.assertTrue(result["isolated_state_cleaned"])
            prompt = json.loads((root / "workdir/fake_prompt.json").read_text())
            self.assertEqual(prompt["system"], "exact system instruction")
            self.assertEqual(
                prompt["model"], {"providerID": "fixture", "modelID": "model"}
            )
            state = json.loads((root / "workdir/fake_state.json").read_text())
            self.assertTrue(state["spawn_child_tool"])
            self.assertTrue(state["system_plugin"])
            self.assertEqual(
                state["METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS"],
                "exact system instruction",
            )
            roots = {
                str(Path(value).parents[0] if key == "OPENCODE_DB" else Path(value))
                for key, value in state.items()
                if key
                not in {
                    "spawn_child_tool",
                    "system_plugin",
                    "METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS",
                }
                and value is not None
            }
            self.assertTrue(all(str(root / "state/opencode_runtime") in value for value in roots))
            self.assertFalse((root / "state/opencode_runtime").exists())

    def test_mcp_translation_and_sensitive_event_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mcp = {
                "supergpqa": {
                    "command": sys.executable,
                    "args": ["-m", "utils.supergpqa_mcp"],
                    "cwd": str(PROJECT_ROOT),
                    "env": {"METALANGUAGE_SUPERGPQA_CONTEXT": str(root / "private.json")},
                    "required": True,
                    "enabled_tools": ["submit_solution"],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 1,
                    "tool_timeout_sec": 30,
                }
            }
            result = self._run(
                root,
                mcp=mcp,
                sensitive=(("supergpqa", "submit_solution"),),
            )
            self.assertEqual(result["status"], "completed")
            events = Path(str(result["events_path"])).read_text()
            self.assertNotIn("SECRET_ARGUMENT", events)
            self.assertNotIn("SECRET_RESULT", events)
            self.assertIn('"redacted": true', events)
            self.assertIn('"event": "mcp_ready"', events)
            durable_request = json.loads(
                Path(str(result["request_path"])).read_text()
            )
            durable_server = durable_request["mcp_servers"]["supergpqa"]
            self.assertNotIn(str(root / "private.json"), json.dumps(durable_server))
            self.assertEqual(
                durable_server["env"]["METALANGUAGE_SUPERGPQA_CONTEXT"],
                {"redacted": True},
            )
            session = json.loads((root / "workdir/fake_session.json").read_text())
            self.assertIn(
                {
                    "permission": "mcp__supergpqa__*",
                    "pattern": "*",
                    "action": "deny",
                },
                session["permission"],
            )
            self.assertIn(
                {
                    "permission": "mcp__supergpqa__submit_solution",
                    "pattern": "*",
                    "action": "allow",
                },
                session["permission"],
            )

    def test_required_mcp_and_enabled_tool_validation_fail_closed(self) -> None:
        def config(command: str, tool: str) -> dict[str, object]:
            return {
                "supergpqa": {
                    "command": command,
                    "args": [],
                    "cwd": str(PROJECT_ROOT),
                    "env": {},
                    "required": True,
                    "enabled_tools": [tool],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 1,
                    "tool_timeout_sec": 30,
                }
            }

        with tempfile.TemporaryDirectory() as temp:
            result = self._run(
                Path(temp), mcp=config("fake-fail", "submit_solution")
            )
            self.assertEqual(result["status"], "error")
            self.assertEqual(
                result["error_code"], "required_mcp_server_unavailable"
            )

        invalid = config(sys.executable, "submit_solution")
        invalid["supergpqa"]["enabled_tools"] = []
        with tempfile.TemporaryDirectory() as temp:
            result = self._run(Path(temp), mcp=invalid)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "invalid_mcp_configuration")

    def test_provider_error_malformed_event_timeout_and_parent_continuation(self) -> None:
        for prompt, expected_status, expected_code in [
            ("__PROVIDER_ERROR__", "error", "ProviderAuthError"),
            ("__MALFORMED__", "error", "malformed_opencode_event"),
            ("__TIMEOUT__", "timeout", "worker_timeout"),
        ]:
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temp:
                result = self._run(Path(temp), prompt=prompt, timeout=1)
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["error_code"], expected_code)
                self.assertTrue(result["isolated_state_cleaned"])
                if prompt == "__TIMEOUT__":
                    server_pid = int(
                        (Path(temp) / "workdir/fake_server.pid").read_text()
                    )
                    self._assert_pid_gone(server_pid)

        with tempfile.TemporaryDirectory() as temp:
            result = self._run(Path(temp), prompt="__SPAWN__")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "parent continued")
            events = Path(str(result["events_path"])).read_text()
            self.assertLess(events.index('"tool": "spawn_child"'), events.index("parent continued"))

    def test_version_guard_and_graceful_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"FAKE_OPENCODE_VERSION": "9.9.9"}
        ):
            result = self._run(Path(temp))
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "unsupported_opencode_version")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workdir = root / "workdir"
            workdir.mkdir()
            request = {
                "opencode_bin": str(self._fake_cli(root)),
                "allowed_versions": ["1.18.18"],
                "model": "fixture/model",
                "cwd": str(workdir),
                "state_root": str(root / "state"),
                "initial_user_text": "__TIMEOUT__",
                "timeout_seconds": 60,
                "startup_timeout_seconds": 2,
                "mcp_servers": {},
                "sensitive_mcp_tools": [],
            }
            process = subprocess.Popen(
                [str(self.bun_bin), str(self.worker_script)],
                cwd=PROJECT_ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps(request))
            process.stdin.close()
            process.stdin = None
            lines: list[str] = []
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if not line:
                    break
                lines.append(line)
                if '"event":"thread_started"' in line:
                    break
            server_pid_path = workdir / "fake_server.pid"
            deadline = time.monotonic() + 5
            while not server_pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            process.send_signal(signal.SIGTERM)
            remaining, stderr = process.communicate(timeout=10)
            lines.append(remaining)
            self.assertNotEqual(process.returncode, 0, stderr)
            payload = "".join(lines)
            self.assertIn('"error_code":"worker_cancelled"', payload)
            server_pid = int(server_pid_path.read_text())
            self._assert_pid_gone(server_pid)

    def test_malformed_runner_stdout_is_not_persisted(self) -> None:
        stream = Buffer()
        state = {
            "final_text": "",
            "thread_id": "",
            "session_id": "",
            "error_code": "",
            "error_message": "",
            "runtime_version": "",
            "malformed_output": False,
        }
        _handle_runner_line(
            "PRIVATE malformed output",
            events_stream=stream,
            progress_callback=None,
            state=state,
        )
        self.assertTrue(state["malformed_output"])
        self.assertNotIn("PRIVATE", stream.value)

    def test_process_group_termination_reaps_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pid_path = Path(temp) / "child.pid"
            script = (
                "import pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(pid_path)],
                start_new_session=True,
            )
            deadline = time.monotonic() + 5
            while not pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            child_pid = int(pid_path.read_text())
            _terminate_process_group(process, grace_seconds=0.2)
            self.assertIsNotNone(process.poll())
            self._assert_pid_gone(child_pid)

    def test_normal_completion_reaps_opencode_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._run(root, prompt="__DESCENDANT__")
            self.assertEqual(result["status"], "completed")
            descendant_pid = int((root / "workdir/fake_descendant.pid").read_text())
            self._assert_pid_gone(descendant_pid)


if __name__ == "__main__":
    unittest.main()

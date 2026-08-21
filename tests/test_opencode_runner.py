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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from main_loop import WorkerResult, run_opencode_worker
from utils.opencode_runner import (
    _handle_runner_line,
    _rollout_environment,
    _terminate_process_group,
    opencode_worker_script_path,
    normalize_error_code,
    prepare_provider_environment,
    provider_environment_fingerprint,
    resolve_bun_bin,
    resolve_opencode_bin,
    run_opencode_rollout,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_OPENCODE = PROJECT_ROOT / "tests/fixtures/fake_opencode.py"
FAKE_PROVIDER = PROJECT_ROOT / "tests/fixtures/fake_openai_provider.py"
FAKE_MCP = PROJECT_ROOT / "tests/fixtures/fake_stdio_mcp.py"


def _test_provider_config(url: str) -> dict[str, object]:
    return {
        "test": {
            "name": "Test",
            "id": "test",
            "env": [],
            "npm": "@ai-sdk/openai-compatible",
            "models": {
                "test-model": {
                    "id": "test-model",
                    "name": "Test Model",
                    "attachment": True,
                    "reasoning": False,
                    "temperature": False,
                    "tool_call": True,
                    "release_date": "2025-01-01",
                    "limit": {"context": 100_000, "output": 10_000},
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "cost": {"input": 0, "output": 0},
                    "options": {},
                }
            },
            "options": {"apiKey": "test-key", "baseURL": url},
        }
    }


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

    def _start_provider(
        self,
        root: Path,
        *,
        mode: str,
        tool: str = "spawn_child",
        arguments: dict[str, object] | None = None,
    ) -> tuple[subprocess.Popen[str], str, Path]:
        capture = root / "provider_capture.jsonl"
        process = subprocess.Popen(
            [sys.executable, "-B", str(FAKE_PROVIDER)],
            cwd=PROJECT_ROOT,
            env={
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "FAKE_PROVIDER_CAPTURE": str(capture),
                "FAKE_PROVIDER_MODE": mode,
                "FAKE_PROVIDER_TOOL": tool,
                "FAKE_PROVIDER_TOOL_ARGS": json.dumps(arguments or {}),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert process.stdout is not None
        url = process.stdout.readline().strip()
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        return process, url, capture

    def _stop_provider(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    def _run_real(
        self,
        root: Path,
        *,
        url: str,
        prompt: str,
        continuation: Path | None = None,
        mcp: dict[str, object] | None = None,
        sensitive: tuple[tuple[str, str], ...] = (),
        timeout: int = 30,
        provider_env_names: tuple[str, ...] = (),
    ) -> dict[str, object]:
        workdir = root / "workdir"
        workdir.mkdir(exist_ok=True)
        return run_opencode_rollout(
            worker_script=self.worker_script,
            bun_bin=self.bun_bin,
            opencode_bin=resolve_opencode_bin(None),
            model="test/test-model",
            workdir=workdir,
            control_dir=root / "control",
            worker_state_dir=root / "state",
            timeout_seconds=timeout,
            initial_user_text=prompt,
            system_instructions="EXACT OFFLINE SYSTEM",
            continuation_context_path=continuation,
            benchmark_mcp_servers=mcp,
            sensitive_mcp_tools=sensitive,
            allowed_versions=("1.18.19",),
            startup_timeout_seconds=30,
            provider_env_names=provider_env_names,
            extra_environment={"METALANGUAGE_OPENCODE_OFFLINE_TEST": "1"},
            test_provider_config=_test_provider_config(url),
            sandbox_read_only_roots=(PROJECT_ROOT,),
            sandbox_writable_roots=(root,),
        )

    def _spawn_context(self, root: Path) -> Path:
        workdir = root / "workdir"
        workdir.mkdir(exist_ok=True)
        seed = workdir / "seed"
        seed.mkdir()
        (seed / "README.md").write_text("child workspace\n")
        context = root / "continuation.json"
        context.write_text(
            json.dumps(
                {
                    "workdir": str(workdir),
                    "spawn_slots_path": str(root / "spawn_slots.json"),
                    "spawn_slots_dir": str(root / "spawn_slots"),
                    "task_id": "offline-task",
                    "task_index": 0,
                    "rollout_index": 0,
                    "rollout_username": "rollout-0",
                    "instance_uuid": "offline-parent",
                    "population_size": 1,
                    "generation": 0,
                    "seed": 1,
                    "progress_log": str(root / "progress.jsonl"),
                }
            )
        )
        return context

    def _assert_pid_gone(self, pid: int) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        self.fail(f"process {pid} survived cleanup")

    def _runtime_pid(self, result: dict[str, object]) -> int:
        events = [
            json.loads(line)
            for line in Path(str(result["events_path"])).read_text().splitlines()
        ]
        return int(
            next(
                event["pid"]
                for event in events
                if event.get("event") == "runtime_process_started"
            )
        )

    def _run(
        self,
        root: Path,
        *,
        prompt: str = "ordinary prompt",
        mcp: dict[str, object] | None = None,
        sensitive: tuple[tuple[str, str], ...] = (),
        timeout: int = 5,
        agent: str | None = None,
        variant: str | None = None,
        provider_env_names: tuple[str, ...] = (),
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
            agent=agent,
            variant=variant,
            allowed_versions=("1.18.19",),
            startup_timeout_seconds=2,
            provider_env_names=provider_env_names,
            extra_environment={
                name: value
                for name in (
                    "FAKE_OPENCODE_SSE_HANG",
                    "FAKE_OPENCODE_STARTUP_HANG",
                    "FAKE_OPENCODE_VERSION",
                )
                if (value := os.environ.get(name)) is not None
            },
        )

    def test_vertical_slice_exact_prompt_state_isolation_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._run(root, agent="build", variant="high")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "fixture final")
            self.assertEqual(result["runtime_version"], "1.18.19")
            self.assertTrue(result["isolated_state_cleaned"])
            prompt = json.loads((root / "workdir/fake_prompt.json").read_text())
            self.assertEqual(prompt["system"], "exact system instruction")
            self.assertEqual(
                prompt["model"], {"providerID": "fixture", "modelID": "model"}
            )
            self.assertEqual(prompt["agent"], "build")
            self.assertEqual(prompt["variant"], "high")
            state = json.loads((root / "workdir/fake_state.json").read_text())
            self.assertTrue(state["spawn_child_tool"])
            self.assertTrue(state["system_plugin"])
            self.assertTrue(state["prepared_dependencies"])
            self.assertTrue(state["npm_offline"])
            self.assertNotIn("SSH_AUTH_SOCK", state["environment_names"])
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", state["environment_names"])
            self.assertFalse(state["unrelated_home_visible"])
            self.assertTrue(state["project_env_masked"])
            self.assertEqual(
                state["METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS"],
                "exact system instruction",
            )
            self.assertTrue(
                state["METALANGUAGE_SPAWN_CHILD_ENDPOINT"].startswith(
                    "http://127.0.0.1:"
                )
            )
            self.assertIsNone(state["METALANGUAGE_SPAWN_CHILD_HANDLER_COMMAND"])
            self.assertIsNone(state["METALANGUAGE_OPENCODE_WORKER_SCRIPT"])
            roots = {
                str(Path(value).parents[0] if key == "OPENCODE_DB" else Path(value))
                for key, value in state.items()
                if key
                not in {
                    "spawn_child_tool",
                    "system_plugin",
                    "prepared_dependencies",
                    "npm_offline",
                    "server_port",
                    "auth_fingerprint",
                    "environment_names",
                    "unrelated_home_visible",
                    "project_env_masked",
                    "METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS",
                    "METALANGUAGE_SPAWN_CHILD_ENDPOINT",
                    "METALANGUAGE_SPAWN_CHILD_HANDLER_COMMAND",
                    "METALANGUAGE_OPENCODE_WORKER_SCRIPT",
                    "path_environment",
                    "credential_mount_names",
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
            ("__HTTP_ERROR__", "error", "opencode_http_error"),
            ("__TIMEOUT__", "timeout", "worker_timeout"),
        ]:
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temp:
                result = self._run(Path(temp), prompt=prompt, timeout=1)
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["error_code"], expected_code)
                self.assertTrue(result["isolated_state_cleaned"])
                durable = Path(str(result["events_path"])).read_text()
                self.assertNotIn("PRIVATE", durable)
                if prompt == "__TIMEOUT__":
                    self._assert_pid_gone(self._runtime_pid(result))

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
            result = run_opencode_rollout(
                worker_script=self.worker_script,
                bun_bin=self.bun_bin,
                opencode_bin=self._fake_cli(root),
                model="fixture/model",
                workdir=workdir,
                control_dir=root / "control",
                worker_state_dir=root / "state",
                timeout_seconds=2,
                initial_user_text="ordinary prompt",
                allowed_versions=("1.18.19",),
                allowed_bun_versions=("9.9.9",),
                startup_timeout_seconds=2,
            )
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_code"], "unsupported_bun_version")

        for variable, expected_code in (
            ("FAKE_OPENCODE_STARTUP_HANG", "opencode_start_timeout"),
            ("FAKE_OPENCODE_SSE_HANG", "opencode_http_timeout"),
        ):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as temp, patch.dict(
                os.environ,
                {variable: "1"},
            ):
                result = self._run(Path(temp))
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["error_code"], expected_code)
                self._assert_pid_gone(self._runtime_pid(result))

        with patch("utils.opencode_runner.shutil.which", return_value=None):
            self.assertEqual(
                resolve_opencode_bin(None),
                (Path.home() / ".opencode/bin/opencode").resolve(),
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workdir = root / "workdir"
            workdir.mkdir()
            request = {
                "opencode_bin": str(self._fake_cli(root)),
                "allowed_versions": ["1.18.19"],
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

    def test_abrupt_worker_death_reaps_bubblewrap_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workdir = root / "workdir"
            workdir.mkdir()
            request = {
                "opencode_bin": str(self._fake_cli(root)),
                "allowed_versions": ["1.18.19"],
                "allowed_bun_versions": ["1.3.14"],
                "model": "fixture/model",
                "cwd": str(workdir),
                "state_root": str(root / "state"),
                "initial_user_text": "__TIMEOUT__",
                "timeout_seconds": 60,
                "startup_timeout_seconds": 5,
                "mcp_servers": {},
                "sensitive_mcp_tools": [],
                "sandbox": {
                    "mode": "bubblewrap",
                    "network": "allow",
                    "bubblewrap_bin": "/usr/bin/bwrap",
                    "read_only_roots": [str(PROJECT_ROOT)],
                    "writable_roots": [str(root)],
                },
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
            runtime_pid = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                line = process.stdout.readline()
                if not line:
                    break
                event = json.loads(line)
                if event.get("event") == "runtime_process_started":
                    runtime_pid = int(event["pid"])
                if event.get("event") == "thread_started":
                    break
            self.assertIsNotNone(runtime_pid)
            process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            self._assert_pid_gone(int(runtime_pid))

    def test_unrelated_host_secrets_are_not_inherited(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {"UNRELATED_HOST_SECRET": "sk-PRIVATE-HOST-SECRET"},
        ):
            root = Path(temp)
            result = self._run(root)
            self.assertEqual(result["status"], "completed")
            state = json.loads((root / "workdir/fake_state.json").read_text())
            self.assertNotIn("UNRELATED_HOST_SECRET", state["environment_names"])

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-PRIVATE-EXPLICIT-PROVIDER",
                "UNRELATED_HOST_SECRET": "sk-PRIVATE-HOST-SECRET",
            },
        ):
            env = _rollout_environment(
                bun_bin=self.bun_bin,
                opencode_bin=resolve_opencode_bin(None),
                provider_env_names=("OPENAI_API_KEY",),
            )
            self.assertEqual(env["OPENAI_API_KEY"], "sk-PRIVATE-EXPLICIT-PROVIDER")
            self.assertNotIn("UNRELATED_HOST_SECRET", env)
            self.assertNotIn("HOME", env)
            first = provider_environment_fingerprint(("OPENAI_API_KEY",))
            os.environ["OPENAI_API_KEY"] = "sk-PRIVATE-CHANGED-PROVIDER"
            self.assertNotEqual(
                first,
                provider_environment_fingerprint(("OPENAI_API_KEY",)),
            )

    def test_path_credentials_are_exact_read_only_mounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            credential_parent = root / "credential parent with spaces"
            credential_parent.mkdir()
            credential = credential_parent / "google key.json"
            credential.write_text('{"private_key":"fixture"}\n')
            alias = root / "credential-link.json"
            alias.symlink_to(credential)
            sibling = credential_parent / "not-mounted.txt"
            sibling.write_text("must stay hidden")
            cert_dir = root / "certificate directory"
            cert_dir.mkdir()
            (cert_dir / "root.pem").write_text("fixture certificate")
            cert_file = root / "certificate file.pem"
            cert_file.write_text("fixture certificate file")
            requests_bundle = root / "requests ca bundle.pem"
            requests_bundle.write_text("fixture requests bundle")
            with patch.dict(
                os.environ,
                {
                    "GOOGLE_APPLICATION_CREDENTIALS": str(alias),
                    "SSL_CERT_DIR": str(cert_dir),
                    "SSL_CERT_FILE": str(cert_file),
                    "REQUESTS_CA_BUNDLE": str(requests_bundle),
                },
            ):
                result = self._run(
                    root,
                    provider_env_names=("GOOGLE_APPLICATION_CREDENTIALS",),
                )
            self.assertEqual(result["status"], "completed")
            state = json.loads((root / "workdir/fake_state.json").read_text())
            mounted = state["path_environment"]
            self.assertEqual(
                mounted["GOOGLE_APPLICATION_CREDENTIALS"]["value"],
                "/run/metalanguage/credentials/GOOGLE_APPLICATION_CREDENTIALS",
            )
            self.assertTrue(mounted["GOOGLE_APPLICATION_CREDENTIALS"]["exists"])
            self.assertFalse(mounted["GOOGLE_APPLICATION_CREDENTIALS"]["writable"])
            self.assertEqual(
                mounted["SSL_CERT_DIR"]["value"],
                "/run/metalanguage/credentials/SSL_CERT_DIR",
            )
            self.assertTrue(mounted["SSL_CERT_DIR"]["is_dir"])
            self.assertFalse(mounted["SSL_CERT_DIR"]["writable"])
            self.assertFalse(mounted["SSL_CERT_FILE"]["is_dir"])
            self.assertFalse(mounted["SSL_CERT_FILE"]["writable"])
            self.assertFalse(mounted["REQUESTS_CA_BUNDLE"]["is_dir"])
            self.assertFalse(mounted["REQUESTS_CA_BUNDLE"]["writable"])
            self.assertEqual(
                state["credential_mount_names"],
                [
                    "GOOGLE_APPLICATION_CREDENTIALS",
                    "REQUESTS_CA_BUNDLE",
                    "SSL_CERT_DIR",
                    "SSL_CERT_FILE",
                ],
            )
            self.assertNotIn(str(credential_parent), json.dumps(state))

    def test_path_credentials_reject_missing_wrong_kind_and_nested_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases: list[tuple[str, Path]] = [
                ("GOOGLE_APPLICATION_CREDENTIALS", root / "missing.json"),
                ("GOOGLE_APPLICATION_CREDENTIALS", root),
            ]
            file_path = root / "cert.pem"
            file_path.write_text("cert")
            cases.append(("SSL_CERT_DIR", file_path))
            for name, value in cases:
                with self.subTest(name=name, value=value), patch.dict(
                    os.environ, {name: str(value)}
                ):
                    with self.assertRaisesRegex(ValueError, "OpenCode path environment"):
                        prepare_provider_environment((name,), sandbox_mode="bubblewrap")

            directory = root / "certs"
            directory.mkdir()
            (directory / "escape.pem").symlink_to(file_path)
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(directory)}):
                with self.assertRaisesRegex(ValueError, "contains a symlink"):
                    prepare_provider_environment((), sandbox_mode="bubblewrap")

    def test_production_wrapper_forwards_all_opencode_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mount = (root / "credential", Path("/run/metalanguage/credentials/TEST"))
            paths = {
                "worker_script": root / "worker.ts",
                "bun_bin": root / "bun",
                "opencode_bin": root / "opencode",
                "workdir": root / "workdir",
                "control_dir": root / "control",
                "worker_state_dir": root / "state",
                "bubblewrap_bin": root / "bwrap",
            }
            expected = {
                "final_text": "ok",
                "status": "completed",
                "stop_reason": "final_message",
                "error_code": None,
                "error_message": None,
            }
            with patch("main_loop.run_opencode_rollout", return_value=expected) as rollout:
                result = run_opencode_worker(
                    **paths,
                    model="provider/model",
                    timeout_seconds=17,
                    initial_user_text="exact prompt",
                    system_instructions="exact system",
                    allowed_versions=("1.18.19",),
                    allowed_bun_versions=("1.3.14",),
                    startup_timeout_seconds=19,
                    provider_env_names=("OPENAI_API_KEY",),
                    provider_environment={"OPENAI_API_KEY": "secret"},
                    sandbox_mode="bubblewrap",
                    sandbox_network="allow",
                    sandbox_read_only_roots=(root / "readonly",),
                    sandbox_read_only_mounts=(mount,),
                    sandbox_writable_roots=(root / "writable",),
                    sandbox_masked_paths=(root / ".env",),
                )
            self.assertEqual(result.status, "completed")
            kwargs = rollout.call_args.kwargs
            for key in (
                "allowed_bun_versions",
                "provider_env_names",
                "provider_environment",
                "sandbox_mode",
                "sandbox_network",
                "bubblewrap_bin",
                "sandbox_read_only_roots",
                "sandbox_read_only_mounts",
                "sandbox_writable_roots",
                "sandbox_masked_paths",
            ):
                self.assertIn(key, kwargs)
            self.assertEqual(kwargs["sandbox_read_only_mounts"], (mount,))

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

        _handle_runner_line(
            json.dumps(
                {
                    "event": "error",
                    "error_code": "ProviderError",
                    "error_message": "upstream sk-PRIVATE-ADVERSARIAL",
                }
            ),
            events_stream=stream,
            progress_callback=None,
            state=state,
        )
        self.assertNotIn("PRIVATE", stream.value)
        adversarial = _handle_runner_line(
            json.dumps(
                {
                    "event": "error",
                    "error_code": "ProviderBearer_sk-PRIVATE-" + "A" * 10_000,
                    "error_message": "another private payload",
                }
            ),
            events_stream=stream,
            progress_callback=None,
            state=state,
        )
        self.assertEqual(adversarial["error_code"], "unknown")
        self.assertEqual(normalize_error_code("ProviderAuthError"), "ProviderAuthError")
        self.assertNotIn("PRIVATE", stream.value)

    def test_two_and_eight_workers_have_unique_isolation_and_no_lingering_processes(self) -> None:
        for count in (2, 8):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)

                def launch(index: int) -> tuple[dict[str, object], Path]:
                    child = root / f"worker-{index}"
                    child.mkdir()
                    prompt = "__TIMEOUT__" if index == count - 1 else "ordinary prompt"
                    return self._run(child, prompt=prompt, timeout=1), child

                with ThreadPoolExecutor(max_workers=count) as executor:
                    pairs = list(executor.map(launch, range(count)))
                ports: set[int] = set()
                auth: set[str] = set()
                homes: set[str] = set()
                for index, (result, child) in enumerate(pairs):
                    expected = "timeout" if index == count - 1 else "completed"
                    self.assertEqual(result["status"], expected)
                    state = json.loads((child / "workdir/fake_state.json").read_text())
                    self.assertTrue(state["prepared_dependencies"])
                    self.assertTrue(state["npm_offline"])
                    ports.add(int(state["server_port"]))
                    auth.add(str(state["auth_fingerprint"]))
                    homes.add(str(state["HOME"]))
                    self._assert_pid_gone(self._runtime_pid(result))
                self.assertEqual(len(ports), count)
                self.assertEqual(len(auth), count)
                self.assertEqual(len(homes), count)

    def test_real_opencode_offline_system_spawn_and_parent_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process, url, capture = self._start_provider(
                root,
                mode="spawn",
                arguments={"prompt": "child task", "workspace_dir": "seed"},
            )
            try:
                context = self._spawn_context(root)
                result = self._run_real(
                    root,
                    url=url,
                    prompt="invoke spawn_child",
                    continuation=context,
                )
            finally:
                self._stop_provider(process)
            requests = [json.loads(line) for line in capture.read_text().splitlines()]
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "parent continued")
            self.assertTrue(
                (root / "spawn_slots.json").is_file(),
                requests[-1]["messages"][-1]["content"],
            )
            slots = json.loads((root / "spawn_slots.json").read_text())
            self.assertEqual(slots["spawned_child_count"], 1)
            self.assertEqual(requests[0]["messages"][0], {"role": "system", "content": "EXACT OFFLINE SYSTEM"})
            self.assertEqual(requests[-1]["messages"][-1]["role"], "tool")
            self.assertIn('"success":true', requests[-1]["messages"][-1]["content"])

    def test_real_opencode_offline_mcp_allowlist_image_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process, url, capture = self._start_provider(
                root,
                mode="mcp",
                tool="mcp__fixture__image",
            )
            mcp = {
                "fixture": {
                    "command": sys.executable,
                    "args": ["-B", str(FAKE_MCP)],
                    "cwd": str(PROJECT_ROOT),
                    "env": {
                        "FAKE_MCP_ENV_FILE": str(root / "mcp.env"),
                        "FAKE_MCP_PID_FILE": str(root / "mcp.pid"),
                    },
                    "required": True,
                    "enabled_tools": ["image"],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 10,
                }
            }
            try:
                with patch.dict(
                    os.environ,
                    {"OPENAI_API_KEY": "sk-PRIVATE-NOT-FOR-MCP"},
                ):
                    result = self._run_real(
                        root,
                        url=url,
                        prompt="use the image tool",
                        mcp=mcp,
                        provider_env_names=("OPENAI_API_KEY",),
                    )
            finally:
                self._stop_provider(process)
            self.assertEqual(result["status"], "completed")
            events = Path(str(result["events_path"])).read_text()
            self.assertIn('"event": "mcp_ready"', events)
            self.assertNotIn("iVBOR", events)
            requests = [json.loads(line) for line in capture.read_text().splitlines()]
            names = {
                tool["function"]["name"]
                for tool in requests[0]["tools"]
                if tool.get("type") == "function"
            }
            self.assertIn("mcp__fixture__image", names)
            self.assertNotIn("mcp__fixture__secret", names)
            self.assertIn("data:image/png;base64", json.dumps(requests[-1]))
            self.assertIn("resource fixture", json.dumps(requests[-1]))
            self.assertTrue((root / "mcp.pid").is_file())
            mcp_environment = (root / "mcp.env").read_text().splitlines()
            self.assertIn("FAKE_MCP_ENV_FILE", mcp_environment)
            self.assertIn("FAKE_MCP_PID_FILE", mcp_environment)
            self.assertNotIn("OPENCODE_SERVER_PASSWORD", mcp_environment)
            self.assertNotIn("OPENCODE_AUTH_CONTENT", mcp_environment)
            self.assertNotIn("OPENAI_API_KEY", mcp_environment)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process, url, _capture = self._start_provider(
                root,
                mode="mcp",
                tool="mcp__fixture__secret",
                arguments={"answer": "sk-PRIVATE-MCP-ARGUMENT"},
            )
            mcp["fixture"] = {
                **mcp["fixture"],
                "env": {
                    "FAKE_MCP_ENV_FILE": str(root / "mcp.env"),
                    "FAKE_MCP_PID_FILE": str(root / "mcp.pid"),
                },
                "enabled_tools": ["secret"],
            }
            try:
                result = self._run_real(
                    root,
                    url=url,
                    prompt="use the secret tool",
                    mcp=mcp,
                    sensitive=(("fixture", "secret"),),
                )
            finally:
                self._stop_provider(process)
            events = Path(str(result["events_path"])).read_text()
            self.assertEqual(result["status"], "completed")
            self.assertNotIn("PRIVATE", events)
            self.assertIn('"redacted": true', events)

    def test_real_opencode_offline_mcp_timeout_cleans_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process, url, _capture = self._start_provider(
                root,
                mode="mcp",
                tool="mcp__fixture__slow",
                arguments={"seconds": 30},
            )
            mcp = {
                "fixture": {
                    "command": sys.executable,
                    "args": ["-B", str(FAKE_MCP)],
                    "cwd": str(PROJECT_ROOT),
                    "env": {"FAKE_MCP_PID_FILE": str(root / "mcp.pid")},
                    "required": True,
                    "enabled_tools": ["slow"],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 60,
                }
            }
            try:
                result = self._run_real(
                    root,
                    url=url,
                    prompt="start the slow tool",
                    mcp=mcp,
                    timeout=2,
                )
            finally:
                self._stop_provider(process)
            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["error_code"], "worker_timeout")
            self.assertTrue(result["isolated_state_cleaned"])
            self.assertTrue((root / "mcp.pid").is_file())
            mcp_pids = [int(pid) for pid in result["mcp_process_pids"]]
            self.assertGreaterEqual(len(mcp_pids), 2)
            for pid in mcp_pids:
                self._assert_pid_gone(pid)
            self._assert_pid_gone(self._runtime_pid(result))

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
            self.assertTrue((root / "workdir/fake_descendant.pid").is_file())
            self._assert_pid_gone(self._runtime_pid(result))


if __name__ == "__main__":
    unittest.main()

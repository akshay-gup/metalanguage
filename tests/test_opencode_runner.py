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
from types import SimpleNamespace
from unittest.mock import patch

from main_loop import (
    WorkerResult,
    canonical_rollout_system_instructions,
    run_opencode_worker,
)
from utils.opencode_runner import (
    MAX_CREDENTIAL_BYTES,
    MAX_CREDENTIAL_DEPTH,
    MAX_CREDENTIAL_FILES,
    MAX_CUSTOM_PROVIDER_LIMIT,
    _handle_runner_line,
    _rollout_environment,
    _terminate_process_group,
    custom_provider_configuration,
    custom_provider_environment_names,
    custom_provider_fingerprint,
    opencode_worker_script_path,
    normalize_error_code,
    prepare_provider_environment,
    provider_environment_fingerprint,
    resolve_bun_bin,
    resolve_opencode_bin,
    run_opencode_rollout,
    validate_opencode_host_primitives,
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


def _custom_provider(**overrides: object) -> dict[str, object] | None:
    values: dict[str, object] = {
        "model": "fixture/model-one",
        "provider_id": "fixture",
        "name": "Fixture Provider",
        "npm": "@ai-sdk/openai-compatible",
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key_env": "FIXTURE_API_KEY",
        "header_env": ("X-Fixture=FIXTURE_HEADER",),
        "context_limit": 8192,
        "output_limit": 1024,
    }
    values.update(overrides)
    return custom_provider_configuration(**values)  # type: ignore[arg-type]


class Buffer:
    def __init__(self) -> None:
        self.value = ""

    def write(self, value: str) -> None:
        self.value += value

    def flush(self) -> None:
        return


class OpenCodeRunnerTests(unittest.TestCase):
    audited_opencode_version = "1.18.21"

    def setUp(self) -> None:
        self.worker_script = opencode_worker_script_path()
        self.bun_bin = resolve_bun_bin(None)

    def test_custom_provider_validation_and_secret_name_collection(self) -> None:
        self.assertIsNone(
            custom_provider_configuration(
                model="openai/model",
                provider_id=None,
                name=None,
                npm=None,
                base_url=None,
                api_key_env=None,
            )
        )
        configured = _custom_provider()
        assert configured is not None
        self.assertEqual(configured["provider_id"], "fixture")
        self.assertEqual(configured["api_mode"], "chat_completions")
        self.assertEqual(configured["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(
            custom_provider_environment_names(configured),
            ("FIXTURE_API_KEY", "FIXTURE_HEADER"),
        )
        self.assertEqual(custom_provider_fingerprint(configured), custom_provider_fingerprint(dict(configured)))
        self.assertNotEqual(
            custom_provider_fingerprint(configured),
            custom_provider_fingerprint({**configured, "base_url": "https://example.test/v1"}),
        )

    def test_custom_provider_rejects_partial_identity_and_package_mismatches(self) -> None:
        required = ("provider_id", "name", "npm", "base_url", "api_key_env")
        for field in required:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "incomplete"):
                _custom_provider(**{field: None})
        for overrides, message in (
            ({"provider_id": "Bad Provider"}, "safe identifier"),
            ({"model": "other/model-one"}, "must match"),
            ({"model": "fixture/model with space"}, "unsupported characters"),
            ({"npm": "@vendor/unaudited"}, "unsupported"),
            ({"name": "bad\nname"}, "invalid characters"),
            ({"name": "x" * 129}, "invalid characters"),
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                _custom_provider(**overrides)

    def test_custom_provider_url_policy(self) -> None:
        for url in (
            "http://localhost:8000/v1/",
            "http://127.1.2.3:8000/v1",
            "http://[::1]:8000/v1",
            "https://provider.example/v1/",
        ):
            with self.subTest(url=url):
                configured = _custom_provider(base_url=url)
                assert configured is not None
                self.assertFalse(str(configured["base_url"]).endswith("/"))
        for url, message in (
            ("http://provider.example/v1", "requires HTTPS"),
            ("ftp://provider.example/v1", "HTTP or HTTPS"),
            ("https:///v1", "with a host"),
            ("https://bad_host/v1", "invalid host"),
            ("https://user:pass@provider.example/v1", "user information"),
            ("https://provider.example/v1?secret=x", "query or fragment"),
            ("https://provider.example/v1#fragment", "query or fragment"),
            ("https://" + "x" * 2050, "invalid length"),
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, message):
                _custom_provider(base_url=url)

    def test_custom_provider_header_environment_and_limit_policy(self) -> None:
        for headers, message in (
            (("missing-separator",), "HEADER=ENV_VAR"),
            (("bad header=FIXTURE_HEADER",), "header name"),
            (("Host=FIXTURE_HEADER",), "transport-controlled"),
            (("Proxy-Authorization=FIXTURE_HEADER",), "transport-controlled"),
            (("X-One=FIXTURE_HEADER", "x-one=OTHER_SECRET"), "duplicate"),
            (("X-One=1INVALID",), "environment variable name"),
            (("X-One=OPENCODE_TOKEN",), "reserved"),
        ):
            with self.subTest(headers=headers), self.assertRaisesRegex(ValueError, message):
                _custom_provider(header_env=headers)
        for environment_name, message in (
            ("1INVALID", "environment variable name"),
            ("METALANGUAGE_SECRET", "reserved"),
            ("SSL_CERT_FILE", "transport-reserved"),
            ("X" * 129, "environment variable name"),
        ):
            with self.subTest(environment_name=environment_name), self.assertRaisesRegex(ValueError, message):
                _custom_provider(api_key_env=environment_name)
        for overrides, message in (
            ({"context_limit": None}, "configured together"),
            ({"output_limit": None}, "configured together"),
            ({"context_limit": 0}, "positive integer"),
            ({"output_limit": True}, "positive integer"),
            ({"context_limit": MAX_CUSTOM_PROVIDER_LIMIT + 1}, "no greater"),
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, message):
                _custom_provider(**overrides)

    def test_custom_provider_direct_runner_requires_exact_named_secret_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            configuration = _custom_provider()
            base = {
                "worker_script": root / "worker.ts",
                "bun_bin": root / "bun",
                "opencode_bin": root / "opencode",
                "model": "fixture/model-one",
                "workdir": root / "workdir",
                "control_dir": root / "control",
                "worker_state_dir": root / "state",
                "timeout_seconds": 1,
                "initial_user_text": "test",
                "sandbox_mode": "unsafe-none",
                "custom_provider": configuration,
            }
            with self.assertRaisesRegex(ValueError, "missing from the named allowlist"):
                run_opencode_rollout(
                    **base,
                    provider_env_names=("FIXTURE_API_KEY",),
                    provider_environment={"FIXTURE_API_KEY": "secret"},
                )
            with self.assertRaisesRegex(ValueError, "outside the named allowlist"):
                run_opencode_rollout(
                    **base,
                    provider_env_names=("FIXTURE_API_KEY", "FIXTURE_HEADER"),
                    provider_environment={
                        "FIXTURE_API_KEY": "secret",
                        "FIXTURE_HEADER": "header",
                        "UNEXPECTED_SECRET": "unexpected",
                    },
                )
            with self.assertRaisesRegex(ValueError, "variables are unset"):
                run_opencode_rollout(
                    **base,
                    provider_env_names=("FIXTURE_API_KEY", "FIXTURE_HEADER"),
                    provider_environment={"FIXTURE_API_KEY": "secret"},
                )

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
        plan: list[dict[str, object]] | None = None,
    ) -> tuple[subprocess.Popen[str], str, Path]:
        capture = root / "provider_capture.jsonl"
        environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "FAKE_PROVIDER_CAPTURE": str(capture),
            "FAKE_PROVIDER_TRANSPORT_CAPTURE": str(root / "provider_transport.jsonl"),
            "FAKE_PROVIDER_MODE": mode,
            "FAKE_PROVIDER_TOOL": tool,
            "FAKE_PROVIDER_TOOL_ARGS": json.dumps(arguments or {}),
            "FAKE_PROVIDER_TOOL_PLAN": json.dumps(plan or []),
        }
        process = subprocess.Popen(
            [sys.executable, "-B", str(FAKE_PROVIDER)],
            cwd=PROJECT_ROOT,
            env=environment,
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
        provider_environment: dict[str, str] | None = None,
        custom_provider: dict[str, object] | None = None,
        model: str = "test/test-model",
        allowed_versions: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        workdir = root / "workdir"
        workdir.mkdir(exist_ok=True)
        return run_opencode_rollout(
            worker_script=self.worker_script,
            bun_bin=self.bun_bin,
            opencode_bin=resolve_opencode_bin(None),
            model=model,
            workdir=workdir,
            control_dir=root / "control",
            worker_state_dir=root / "state",
            timeout_seconds=timeout,
            initial_user_text=prompt,
            system_instructions="EXACT OFFLINE SYSTEM",
            continuation_context_path=continuation,
            benchmark_mcp_servers=mcp,
            sensitive_mcp_tools=sensitive,
            allowed_versions=allowed_versions or (self.audited_opencode_version,),
            startup_timeout_seconds=30,
            provider_env_names=provider_env_names,
            provider_environment=provider_environment,
            custom_provider=custom_provider,
            extra_environment={"METALANGUAGE_OPENCODE_OFFLINE_TEST": "1"},
            test_provider_config=(None if custom_provider is not None else _test_provider_config(url)),
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
        startup_timeout: int = 2,
        system_instructions: str = "exact system instruction",
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
            system_instructions=system_instructions,
            continuation_context_path=root / "continuation.json",
            benchmark_mcp_servers=mcp,
            sensitive_mcp_tools=sensitive,
            agent=agent,
            variant=variant,
            allowed_versions=("1.18.21",),
            startup_timeout_seconds=startup_timeout,
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
            canonical_instructions = canonical_rollout_system_instructions()
            result = self._run(
                root,
                agent="build",
                variant="high",
                system_instructions=canonical_instructions,
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "fixture final")
            self.assertEqual(result["runtime_version"], "1.18.21")
            self.assertTrue(result["isolated_state_cleaned"])
            prompt = json.loads((root / "workdir/fake_prompt.json").read_text())
            self.assertEqual(prompt["system"], canonical_instructions)
            request = json.loads(Path(str(result["request_path"])).read_text())
            self.assertEqual(request["system_instructions"], canonical_instructions)
            self.assertEqual(
                prompt["model"], {"providerID": "fixture", "modelID": "model"}
            )
            self.assertEqual(prompt["agent"], "build")
            self.assertEqual(prompt["variant"], "high")
            self.assertTrue(prompt["messageID"].startswith("msg_"))
            requests = [
                json.loads(line)
                for line in (root / "workdir/fake_http_requests.jsonl").read_text().splitlines()
            ]
            self.assertIn(
                {"method": "POST", "path": "/session/ses_fixture/prompt_async"},
                requests,
            )
            self.assertIn(
                {"method": "GET", "path": "/session/ses_fixture/message"},
                requests,
            )
            self.assertNotIn(
                {"method": "POST", "path": "/session/ses_fixture/message"},
                requests,
            )
            self.assertFalse((root / "workdir/fake_sync_message_used").exists())
            self.assertTrue((root / "workdir/fake_delete").is_file())
            state = json.loads((root / "workdir/fake_state.json").read_text())
            self.assertEqual(state["tool_files"], ["spawn_child.js"])
            self.assertNotIn("send_message.js", state["tool_files"])
            self.assertTrue(state["system_plugin"])
            self.assertTrue(state["prepared_dependencies"])
            self.assertTrue(state["npm_offline"])
            self.assertNotIn("SSH_AUTH_SOCK", state["environment_names"])
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", state["environment_names"])
            self.assertFalse(state["unrelated_home_visible"])
            self.assertTrue(state["project_env_masked"])
            self.assertEqual(
                state["METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS"],
                canonical_instructions,
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
                    "tool_files",
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
            durable_request = json.loads(
                (root / "control/opencode_runner.request.json").read_text()
            )
            self.assertNotIn("peer_communication_handler_command", durable_request)
            self.assertEqual(
                durable_request["spawn_child_handler_command"],
                {"configured": True},
            )

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
                result["error_code"], "benchmark_mcp_bridge_failed"
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
            ("__HTTP_ERROR__", "error", "opencode_prompt_submit_failed"),
            ("__SUBMIT_HANG__", "error", "opencode_prompt_submit_timeout"),
            ("__SSE_DISCONNECT__", "error", "opencode_event_closed"),
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
                    self.assertTrue((Path(temp) / "workdir/fake_abort").is_file())
                    self.assertTrue((Path(temp) / "workdir/fake_delete").is_file())
                    self._assert_pid_gone(self._runtime_pid(result))

        with tempfile.TemporaryDirectory() as temp:
            result = self._run(Path(temp), prompt="__SPAWN__")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "parent continued")
            events = Path(str(result["events_path"])).read_text()
            self.assertLess(events.index('"tool": "spawn_child"'), events.index("parent continued"))

    def test_async_submission_outlives_request_threshold_and_ignores_initial_idle(self) -> None:
        for prompt in ("__LONG_ASYNC__", "__INITIAL_IDLE__"):
            with self.subTest(prompt=prompt), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                started = time.monotonic()
                result = self._run(
                    root,
                    prompt=prompt,
                    timeout=3,
                    startup_timeout=1 if prompt == "__LONG_ASYNC__" else 2,
                )
                self.assertEqual(result["status"], "completed", result)
                self.assertEqual(result["final_text"], "fixture final")
                accepted = float((root / "workdir/fake_prompt_accepted_at").read_text())
                completed = float((root / "workdir/fake_prompt_completed_at").read_text())
                self.assertGreaterEqual(accepted, started)
                if prompt == "__LONG_ASYNC__":
                    self.assertGreaterEqual(completed - accepted, 1.1)
                events = Path(str(result["events_path"])).read_text()
                self.assertEqual(events.count('"event": "turn_started"'), 1)
                self.assertNotIn("wrong turn response", events)
                self.assertFalse((root / "workdir/fake_sync_message_used").exists())

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
                allowed_versions=("1.18.21",),
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
                "allowed_versions": ["1.18.21"],
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
                "allowed_versions": ["1.18.21"],
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

    def test_credential_directory_bounds_loops_and_nested_valid_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = root / "valid"
            leaf = valid
            for index in range(min(3, MAX_CREDENTIAL_DEPTH)):
                leaf = leaf / f"d{index}"
            leaf.mkdir(parents=True)
            (leaf / "ca.pem").write_text("valid")
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(valid)}):
                environment, mounts = prepare_provider_environment((), sandbox_mode="bubblewrap")
            self.assertEqual(environment["SSL_CERT_DIR"], "/run/metalanguage/credentials/SSL_CERT_DIR")
            self.assertEqual(mounts[0][0], valid.resolve())

            too_deep = root / "deep"
            leaf = too_deep
            for index in range(MAX_CREDENTIAL_DEPTH + 1):
                leaf = leaf / f"d{index}"
            leaf.mkdir(parents=True)
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(too_deep)}):
                with self.assertRaisesRegex(ValueError, "depth limit"):
                    prepare_provider_environment((), sandbox_mode="bubblewrap")

            too_many = root / "many"
            too_many.mkdir()
            for index in range(MAX_CREDENTIAL_FILES + 1):
                (too_many / f"{index:05d}").touch()
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(too_many)}):
                with self.assertRaisesRegex(ValueError, "file limit"):
                    prepare_provider_environment((), sandbox_mode="bubblewrap")

            too_large = root / "large"
            too_large.mkdir()
            with (too_large / "bundle").open("wb") as stream:
                stream.truncate(MAX_CREDENTIAL_BYTES + 1)
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(too_large)}):
                with self.assertRaisesRegex(ValueError, "byte limit"):
                    prepare_provider_environment((), sandbox_mode="bubblewrap")

            loop = root / "loop"
            loop.mkdir()
            (loop / "self").symlink_to(loop)
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(loop)}):
                with self.assertRaisesRegex(ValueError, "contains a symlink"):
                    prepare_provider_environment((), sandbox_mode="bubblewrap")

            external = root / "external.pem"
            external.write_text("external")
            escaped = root / "escaped"
            escaped.mkdir()
            (escaped / "outside.pem").symlink_to(external)
            with patch.dict(os.environ, {"SSL_CERT_DIR": str(escaped)}):
                with self.assertRaisesRegex(ValueError, "contains a symlink"):
                    prepare_provider_environment((), sandbox_mode="bubblewrap")

    def test_linux_proc_and_bubblewrap_primitives_fail_closed(self) -> None:
        with patch("utils.opencode_runner.sys.platform", "darwin"):
            with self.assertRaisesRegex(RuntimeError, "requires Linux"):
                validate_opencode_host_primitives(Path("/usr/bin/bwrap"))
        with patch(
            "utils.opencode_runner.subprocess.run",
            return_value=SimpleNamespace(returncode=1),
        ):
            with self.assertRaisesRegex(RuntimeError, "primitives are unavailable"):
                validate_opencode_host_primitives(Path("/usr/bin/bwrap"))

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
            custom_provider = _custom_provider()
            with patch("main_loop.run_opencode_rollout", return_value=expected) as rollout:
                result = run_opencode_worker(
                    **paths,
                    model="provider/model",
                    timeout_seconds=17,
                    initial_user_text="exact prompt",
                    system_instructions="exact system",
                    allowed_versions=("1.18.21",),
                    allowed_bun_versions=("1.3.14",),
                    startup_timeout_seconds=19,
                    provider_env_names=("OPENAI_API_KEY",),
                    provider_environment={"OPENAI_API_KEY": "secret"},
                    custom_provider=custom_provider,
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
                "custom_provider",
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
            self.assertEqual(kwargs["custom_provider"], custom_provider)

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

    def test_real_installed_opencode_two_and_eight_worker_concurrency(self) -> None:
        for count in (2, 8):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                providers: list[subprocess.Popen[str]] = []
                urls: list[str] = []
                captures: list[Path] = []
                try:
                    for index in range(count):
                        child = root / f"worker-{index}"
                        child.mkdir()
                        provider, url, capture = self._start_provider(child, mode="final")
                        providers.append(provider)
                        urls.append(url)
                        captures.append(capture)

                    def launch(index: int) -> dict[str, object]:
                        child = root / f"worker-{index}"
                        return self._run_real(
                            child,
                            url=urls[index],
                            prompt=f"real concurrent worker {index}",
                            timeout=30,
                        )

                    with ThreadPoolExecutor(max_workers=count) as executor:
                        results = list(executor.map(launch, range(count)))
                finally:
                    for provider in providers:
                        self._stop_provider(provider)

                ports: set[int] = set()
                auth: set[str] = set()
                state_roots: set[str] = set()
                runtime_pids: set[int] = set()
                for index, result in enumerate(results):
                    self.assertEqual(result["status"], "completed", result)
                    self.assertEqual(result["final_text"], "offline final assistant")
                    self.assertEqual(result["runtime_version"], self.audited_opencode_version)
                    self.assertTrue(result["isolated_state_cleaned"])
                    events = [
                        json.loads(line)
                        for line in Path(str(result["events_path"])).read_text().splitlines()
                    ]
                    isolation = next(event for event in events if event.get("event") == "isolation_verified")
                    ports.add(int(isolation["server_port"]))
                    auth.add(str(isolation["auth_sha256"]))
                    runtime_pid = int(next(event["pid"] for event in events if event.get("event") == "runtime_process_started"))
                    runtime_pids.add(runtime_pid)
                    self._assert_pid_gone(runtime_pid)
                    request = json.loads(Path(str(result["request_path"])).read_text())
                    state_roots.add(str(request["state_root"]))
                    self.assertFalse((root / f"worker-{index}/state/opencode_runtime").exists())
                    self.assertTrue(captures[index].is_file())
                self.assertEqual(len(ports), count)
                self.assertEqual(len(auth), count)
                self.assertEqual(len(state_roots), count)
                self.assertEqual(len(runtime_pids), count)

    def test_real_installed_opencode_custom_provider_chat_and_responses_modes(self) -> None:
        for npm, expected_mode, expected_path in (
            ("@ai-sdk/openai-compatible", "chat_completions", "/v1/chat/completions"),
            ("@ai-sdk/openai", "responses", "/v1/responses"),
        ):
            with self.subTest(npm=npm), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                provider, url, _capture = self._start_provider(root, mode="final")
                configuration = _custom_provider(
                    npm=npm,
                    base_url=url,
                    api_key_env="CUSTOM_API_KEY",
                    header_env=("X-Custom-Secret=CUSTOM_HEADER_SECRET",),
                    context_limit=16384,
                    output_limit=2048,
                )
                assert configuration is not None
                self.assertEqual(configuration["api_mode"], expected_mode)
                secrets = {
                    "CUSTOM_API_KEY": "sk-CUSTOM-PROVIDER-PRIVATE",
                    "CUSTOM_HEADER_SECRET": "header-CUSTOM-PROVIDER-PRIVATE",
                }
                try:
                    with patch.dict(os.environ, secrets):
                        result = self._run_real(
                            root,
                            url=url,
                            prompt="custom provider final response",
                            model="fixture/model-one",
                            provider_env_names=tuple(secrets),
                            custom_provider=configuration,
                        )
                finally:
                    self._stop_provider(provider)
                self.assertEqual(result["status"], "completed", result)
                self.assertEqual(result["final_text"], "offline final assistant")
                transport = [
                    json.loads(line)
                    for line in (root / "provider_transport.jsonl").read_text().splitlines()
                ]
                self.assertEqual(transport[0]["path"], expected_path)
                self.assertEqual(transport[0]["model"], "model-one")
                self.assertEqual(
                    transport[0]["headers"]["authorization"],
                    "Bearer sk-CUSTOM-PROVIDER-PRIVATE",
                )
                self.assertEqual(
                    transport[0]["headers"]["x-custom-secret"],
                    "header-CUSTOM-PROVIDER-PRIVATE",
                )
                for artifact_key in ("request_path", "events_path", "stderr_path"):
                    durable = Path(str(result[artifact_key])).read_text()
                    self.assertNotIn("CUSTOM-PROVIDER-PRIVATE", durable)
                request = json.loads(Path(str(result["request_path"])).read_text())
                self.assertEqual(request["custom_provider"], configuration)
                self.assertTrue(result["isolated_state_cleaned"])
                self._assert_pid_gone(self._runtime_pid(result))

    def test_two_concurrent_real_custom_provider_rollouts_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            providers: list[subprocess.Popen[str]] = []
            urls: list[str] = []
            try:
                for index in range(2):
                    child = root / f"worker-{index}"
                    child.mkdir()
                    provider, url, _capture = self._start_provider(child, mode="final")
                    providers.append(provider)
                    urls.append(url)

                def launch(index: int) -> dict[str, object]:
                    child = root / f"worker-{index}"
                    api_name = f"CUSTOM_API_KEY_{index}"
                    header_name = f"CUSTOM_HEADER_{index}"
                    configuration = _custom_provider(
                        base_url=urls[index],
                        api_key_env=api_name,
                        header_env=(f"X-Worker={header_name}",),
                    )
                    assert configuration is not None
                    return self._run_real(
                        child,
                        url=urls[index],
                        prompt=f"custom concurrent worker {index}",
                        model="fixture/model-one",
                        provider_env_names=(api_name, header_name),
                        provider_environment={
                            api_name: f"sk-worker-{index}",
                            header_name: f"header-worker-{index}",
                        },
                        custom_provider=configuration,
                    )

                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(launch, range(2)))
            finally:
                for provider in providers:
                    self._stop_provider(provider)
            ports: set[int] = set()
            auth: set[str] = set()
            for index, result in enumerate(results):
                self.assertEqual(result["status"], "completed", result)
                events = [
                    json.loads(line)
                    for line in Path(str(result["events_path"])).read_text().splitlines()
                ]
                isolation = next(event for event in events if event.get("event") == "isolation_verified")
                ports.add(int(isolation["server_port"]))
                auth.add(str(isolation["auth_sha256"]))
                transport = json.loads(
                    (root / f"worker-{index}/provider_transport.jsonl").read_text().splitlines()[0]
                )
                self.assertEqual(transport["headers"]["x-worker"], f"header-worker-{index}")
                self.assertNotIn(f"header-worker-{1 - index}", json.dumps(transport))
                self._assert_pid_gone(self._runtime_pid(result))
            self.assertEqual(len(ports), 2)
            self.assertEqual(len(auth), 2)

    def test_real_custom_provider_http_error_redacts_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            provider, url, _capture = self._start_provider(root, mode="error")
            configuration = _custom_provider(
                base_url=url,
                api_key_env="CUSTOM_API_KEY",
                header_env=("X-Custom-Secret=CUSTOM_HEADER_SECRET",),
            )
            assert configuration is not None
            secrets = {
                "CUSTOM_API_KEY": "sk-REFLECTED-PRIVATE",
                "CUSTOM_HEADER_SECRET": "header-REFLECTED-PRIVATE",
            }
            try:
                result = self._run_real(
                    root,
                    url=url,
                    prompt="trigger provider error",
                    model="fixture/model-one",
                    provider_env_names=tuple(secrets),
                    provider_environment=secrets,
                    custom_provider=configuration,
                )
            finally:
                self._stop_provider(provider)
            self.assertEqual(result["status"], "error", result)
            for artifact_key in ("request_path", "events_path", "stderr_path"):
                durable = Path(str(result[artifact_key])).read_text()
                self.assertNotIn("REFLECTED-PRIVATE", durable)
            self._assert_pid_gone(self._runtime_pid(result))

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

    def test_real_opencode_spawn_retry_then_one_success_and_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            process, url, capture = self._start_provider(
                root,
                mode="spawn",
                plan=[
                    {
                        "tool": "spawn_child",
                        "arguments": {"prompt": "retry child", "workspace_dir": "missing"},
                    },
                    {
                        "tool": "spawn_child",
                        "arguments": {"prompt": "successful child", "workspace_dir": "seed"},
                    },
                ],
            )
            try:
                context = self._spawn_context(root)
                result = self._run_real(
                    root,
                    url=url,
                    prompt="retry spawn_child once",
                    continuation=context,
                )
            finally:
                self._stop_provider(process)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["final_text"], "parent continued")
            requests = [json.loads(line) for line in capture.read_text().splitlines()]
            tool_results = [
                message
                for request in requests
                for message in request.get("messages", [])
                if message.get("role") == "tool"
            ]
            self.assertTrue(any('"retryable":true' in message["content"] for message in tool_results))
            self.assertTrue(any('"success":true' in message["content"] for message in tool_results))
            slots = json.loads((root / "spawn_slots.json").read_text())
            self.assertEqual(slots["spawned_child_count"], 1)

    def test_real_opencode_shell_children_receive_blank_provider_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-PRIVATE-SHELL-INHERITANCE"},
        ):
            root = Path(temp)
            process, url, capture = self._start_provider(
                root,
                mode="mcp",
                tool="bash",
                arguments={
                    "command": (
                        "python3 -c 'import os; "
                        'print(repr(os.getenv("OPENAI_API_KEY")))\''
                    )
                },
            )
            try:
                result = self._run_real(
                    root,
                    url=url,
                    prompt="inspect child environment",
                    provider_env_names=("OPENAI_API_KEY",),
                )
            finally:
                self._stop_provider(process)
            self.assertEqual(result["status"], "completed")
            captured = capture.read_text()
            self.assertNotIn("PRIVATE-SHELL-INHERITANCE", captured)
            requests = [json.loads(line) for line in captured.splitlines()]
            self.assertIn("bash", {tool["function"]["name"] for tool in requests[0]["tools"]})
            self.assertTrue(
                any(
                    message.get("role") == "tool" and "''" in str(message.get("content"))
                    for request in requests
                    for message in request.get("messages", [])
                )
            )

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
            status = (root / "mcp.status").read_text() if (root / "mcp.status").exists() else ""
            if status:
                parent = int(next(line.split()[1] for line in status.splitlines() if line.startswith("PPid:")))
                self.assertNotEqual(parent, self._runtime_pid(result))

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

    def test_real_opencode_external_supergpqa_scoring_and_private_root_denial(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "private-answer.json"
            private.write_text(
                json.dumps(
                    {
                        "id": "task-one",
                        "answer": "B",
                        "answer_letter": "B",
                        "options": ["alpha", "beta", "gamma"],
                    }
                )
            )
            events = root / "benchmark-events.jsonl"
            events.touch(mode=0o600)
            context = root / "supergpqa-context.json"
            context.write_text(
                json.dumps(
                    {
                        "instance_uuid": "offline-supergpqa",
                        "benchmark_events_path": str(events),
                        "generation": 0,
                        "seed": 42,
                        "task_index": 0,
                        "rollout_index": 0,
                        "rollout_username": "offline",
                        "problem_pool_records": [
                            {
                                "task_index": 0,
                                "task_id": "task-one",
                                "problem_uid": "problem-one",
                                "task_markdown": "Question without answer",
                                "private_problem_path": str(private),
                            }
                        ],
                    }
                )
            )
            provider, url, capture = self._start_provider(
                root,
                mode="mcp",
                tool="mcp__supergpqa__submit_solution",
                arguments={"uuid": "problem-one", "answer": "B"},
            )
            mcp = {
                "supergpqa": {
                    "command": sys.executable,
                    "args": ["-m", "utils.supergpqa_mcp"],
                    "cwd": str(PROJECT_ROOT),
                    "env": {"METALANGUAGE_SUPERGPQA_CONTEXT": str(context)},
                    "required": True,
                    "enabled_tools": ["submit_solution"],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 10,
                }
            }
            try:
                result = self._run_real(
                    root,
                    url=url,
                    prompt="score the answer",
                    mcp=mcp,
                    sensitive=(("supergpqa", "submit_solution"),),
                )
            finally:
                self._stop_provider(provider)
            self.assertEqual(result["status"], "completed")
            scored = [json.loads(line) for line in events.read_text().splitlines()]
            self.assertEqual(len(scored), 1)
            self.assertTrue(scored[0]["metadata"]["solved"])
            requests = [json.loads(line) for line in capture.read_text().splitlines()]
            tool_names = {item["function"]["name"] for item in requests[0]["tools"]}
            self.assertNotIn("bash", tool_names)
            self.assertIn("mcp__supergpqa__submit_solution", tool_names)
            durable_request = json.loads(Path(str(result["request_path"])).read_text())
            sandbox = durable_request["sandbox"]
            self.assertNotIn(str(root), sandbox["read_only_roots"])
            self.assertNotIn(str(private), json.dumps(sandbox))
            self.assertNotIn(str(context), json.dumps(sandbox))
            self.assertNotIn("private-answer", Path(str(result["events_path"])).read_text())

    def test_real_opencode_benchmark_policy_denies_external_private_file_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "host-private.txt"
            private.write_text("SUPERGPQA_PRIVATE_SENTINEL")
            provider, url, capture = self._start_provider(
                root,
                mode="mcp",
                plan=[
                    {"tool": "read", "arguments": {"filePath": str(private)}},
                    {"tool": "mcp__fixture__echo", "arguments": {"text": "still connected"}},
                ],
            )
            mcp = {
                "fixture": {
                    "command": sys.executable,
                    "args": ["-B", str(FAKE_MCP)],
                    "cwd": str(PROJECT_ROOT),
                    "env": {},
                    "required": True,
                    "enabled_tools": ["echo"],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 10,
                }
            }
            try:
                result = self._run_real(root, url=url, prompt="attempt private read", mcp=mcp)
            finally:
                self._stop_provider(provider)
            self.assertEqual(result["status"], "completed")
            captured = capture.read_text()
            self.assertNotIn("SUPERGPQA_PRIVATE_SENTINEL", captured)
            requests = [json.loads(line) for line in captured.splitlines()]
            self.assertNotIn("bash", {tool["function"]["name"] for tool in requests[0]["tools"]})
            tool_messages = [
                message
                for request in requests
                for message in request.get("messages", [])
                if message.get("role") == "tool"
            ]
            self.assertGreaterEqual(len(tool_messages), 2)
            self.assertNotIn("SUPERGPQA_PRIVATE_SENTINEL", json.dumps(tool_messages))
            self.assertIn("echo:still connected", captured)

    def test_real_opencode_fake_arc_exact_tools_images_resources_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = [
                {"tool": "mcp__arc_agi__RESET", "arguments": {"game_id": "fake-game"}},
                *[
                    {"tool": f"mcp__arc_agi__ACTION{index}", "arguments": {}}
                    for index in range(1, 6)
                ],
                {"tool": "mcp__arc_agi__ACTION6", "arguments": {"x": 17, "y": 23}},
                {"tool": "mcp__arc_agi__ACTION7", "arguments": {}},
            ]
            provider, url, capture = self._start_provider(root, mode="mcp", plan=plan)
            calls = root / "arc-calls.jsonl"
            mcp = {
                "arc_agi": {
                    "command": sys.executable,
                    "args": ["-B", str(FAKE_MCP)],
                    "cwd": str(PROJECT_ROOT),
                    "env": {
                        "FAKE_MCP_CALLS_FILE": str(calls),
                        "FAKE_MCP_PID_FILE": str(root / "arc-mcp.pid"),
                    },
                    "required": True,
                    "enabled_tools": ["RESET", *[f"ACTION{index}" for index in range(1, 8)]],
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": 20,
                    "tool_timeout_sec": 10,
                }
            }
            try:
                result = self._run_real(root, url=url, prompt="exercise ARC", mcp=mcp, timeout=30)
            finally:
                self._stop_provider(provider)
            self.assertEqual(result["status"], "completed")
            actual = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual([row["tool"] for row in actual], ["RESET", *[f"ACTION{i}" for i in range(1, 8)]])
            self.assertEqual(actual[6]["arguments"], {"x": 17, "y": 23})
            requests = [json.loads(line) for line in capture.read_text().splitlines()]
            schemas = {
                item["function"]["name"]: item["function"]["parameters"]
                for item in requests[0]["tools"]
                if item["function"]["name"].startswith("mcp__arc_agi__")
            }
            self.assertEqual(set(schemas), {f"mcp__arc_agi__{name}" for name in ["RESET", *[f"ACTION{i}" for i in range(1, 8)]]})
            self.assertEqual(set(schemas["mcp__arc_agi__ACTION6"]["required"]), {"x", "y"})
            self.assertIn("data:image/png;base64", json.dumps(requests[-1]))
            self.assertIn("resource fixture", json.dumps(requests[-1]))
            durable = Path(str(result["events_path"])).read_text()
            self.assertNotIn("iVBOR", durable)
            for pid in result["mcp_process_pids"]:
                self._assert_pid_gone(int(pid))

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

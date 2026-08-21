"""Thin Python adapter for the Metalanguage-owned TypeScript/Bun OpenCode worker."""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_WORKER_SCRIPT = PROJECT_ROOT / "workers" / "opencode" / "worker.ts"
SOURCE_AUDITED_OPENCODE_VERSIONS = ("1.18.18", "1.18.19")


def opencode_worker_script_path() -> Path:
    return OPENCODE_WORKER_SCRIPT


def resolve_opencode_worker_script(worker_script: Path | None) -> Path:
    path = worker_script if worker_script is not None else opencode_worker_script_path()
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"OpenCode TypeScript worker does not exist: {path}")
    return path


def resolve_bun_bin(value: Path | None) -> Path:
    if value is None:
        resolved = shutil.which("bun")
        if resolved is None:
            fallback = Path.home() / ".bun" / "bin" / "bun"
            if fallback.is_file() and os.access(fallback, os.X_OK):
                resolved = str(fallback)
        if resolved is None:
            raise FileNotFoundError(
                "Bun was not found in PATH or ~/.bun/bin/bun; it is required by the OpenCode worker"
            )
        value = Path(resolved)
    path = value.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"Bun executable is not executable: {path}")
    return path


def resolve_opencode_bin(value: Path | None) -> Path:
    if value is None:
        resolved = shutil.which("opencode")
        if resolved is None:
            raise FileNotFoundError("opencode was not found in PATH")
        value = Path(resolved)
    path = value.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"OpenCode executable is not executable: {path}")
    return path


def _terminate_process_group(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = 3.0,
) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
    process.wait()


def _kill_runtime_process_group(pid: object) -> None:
    if not isinstance(pid, int) or pid <= 1:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _private_runtime_root(worker_state_dir: Path) -> Path:
    worker_state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(worker_state_dir, 0o700)
    root = worker_state_dir / "opencode_runtime"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700)
    if root.parent.resolve() != worker_state_dir.resolve():
        raise RuntimeError("OpenCode runtime root escaped the rollout state directory")
    return root


def _durable_request(request: dict[str, Any]) -> dict[str, Any]:
    """Return diagnostic request metadata without MCP credentials/arguments."""
    durable = json.loads(json.dumps(request))
    for server in durable.get("mcp_servers", {}).values():
        if not isinstance(server, dict):
            continue
        args = server.get("args")
        if isinstance(args, list) and args:
            server["args"] = {"redacted": True, "count": len(args)}
        env = server.get("env")
        if isinstance(env, dict):
            server["env"] = {key: {"redacted": True} for key in env}
    if "auth_file" in durable:
        durable["auth_file"] = {"configured": True}
    return durable


def run_opencode_rollout(
    *,
    worker_script: Path,
    bun_bin: Path,
    opencode_bin: Path,
    model: str,
    workdir: Path,
    control_dir: Path,
    worker_state_dir: Path,
    timeout_seconds: int,
    initial_user_text: str,
    system_instructions: str | None = None,
    continuation_context_path: Path | None = None,
    benchmark_mcp_servers: dict[str, Any] | None = None,
    sensitive_mcp_tools: tuple[tuple[str, str], ...] = (),
    auth_file: Path | None = None,
    agent: str | None = None,
    variant: str | None = None,
    allowed_versions: tuple[str, ...] = SOURCE_AUDITED_OPENCODE_VERSIONS,
    startup_timeout_seconds: int = 15,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    runtime_root = _private_runtime_root(worker_state_dir)
    control_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(control_dir, 0o700)
    request_path = control_dir / "opencode_runner.request.json"
    stderr_path = control_dir / "opencode_runner.stderr.log"
    events_path = control_dir / "opencode_runner.events.jsonl"
    request: dict[str, Any] = {
        "opencode_bin": str(opencode_bin.resolve()),
        "allowed_versions": list(allowed_versions),
        "model": model,
        "cwd": str(workdir.resolve()),
        "state_root": str(runtime_root),
        "initial_user_text": initial_user_text,
        "timeout_seconds": timeout_seconds,
        "startup_timeout_seconds": startup_timeout_seconds,
        "mcp_servers": benchmark_mcp_servers or {},
        "sensitive_mcp_tools": [
            {"server": server, "tool": tool} for server, tool in sensitive_mcp_tools
        ],
    }
    if system_instructions is not None and system_instructions.strip():
        request["system_instructions"] = system_instructions
    if continuation_context_path is not None:
        request["spawn_child_handler_command"] = [
            sys.executable,
            str(PROJECT_ROOT / "main_loop.py"),
            "--child-tool-handler",
            str(continuation_context_path),
        ]
    if auth_file is not None:
        request["auth_file"] = str(auth_file.resolve())
    if agent:
        request["agent"] = agent
    if variant:
        request["variant"] = variant
    request_path.write_text(
        json.dumps(_durable_request(request), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.chmod(request_path, 0o600)

    state: dict[str, Any] = {
        "final_text": "",
        "thread_id": "",
        "session_id": "",
        "error_code": "",
        "error_message": "",
        "runtime_version": "",
        "runtime_process_pid": None,
        "malformed_output": False,
    }
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    timed_out = False
    return_code = -1
    try:
        with stderr_path.open("w", encoding="utf-8") as stderr_stream, events_path.open(
            "w", encoding="utf-8"
        ) as events_stream:
            os.chmod(stderr_path, 0o600)
            os.chmod(events_path, 0o600)
            process = subprocess.Popen(
                [str(bun_bin.resolve()), str(worker_script.resolve())],
                cwd=PROJECT_ROOT,
                env=os.environ.copy(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_stream,
                text=True,
                encoding="utf-8",
                bufsize=1,
                start_new_session=True,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps(request))
            process.stdin.close()
            deadline = started_at + timeout_seconds + startup_timeout_seconds + 15

            while True:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    for raw_line in remaining.splitlines():
                        _handle_runner_line(
                            raw_line,
                            events_stream=events_stream,
                            progress_callback=progress_callback,
                            state=state,
                        )
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    _terminate_process_group(process)
                    remaining = process.stdout.read()
                    for raw_line in remaining.splitlines():
                        _handle_runner_line(
                            raw_line,
                            events_stream=events_stream,
                            progress_callback=progress_callback,
                            state=state,
                        )
                    break
                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if not ready:
                    continue
                raw_line = process.stdout.readline()
                if raw_line:
                    _handle_runner_line(
                        raw_line,
                        events_stream=events_stream,
                        progress_callback=progress_callback,
                        state=state,
                    )
            return_code = process.wait()
    except BaseException:
        if process is not None:
            _terminate_process_group(process)
        raise
    finally:
        _kill_runtime_process_group(state["runtime_process_pid"])
        if runtime_root.parent.resolve() == worker_state_dir.resolve():
            shutil.rmtree(runtime_root, ignore_errors=True)

    metadata = {
        "thread_id": state["thread_id"] or None,
        "session_id": state["session_id"] or None,
        "runtime_version": state["runtime_version"] or None,
        "request_path": str(request_path),
        "stderr_path": str(stderr_path),
        "events_path": str(events_path),
        "isolated_state_cleaned": not runtime_root.exists(),
    }
    if timed_out:
        return {
            "final_text": state["final_text"],
            "status": "timeout",
            "stop_reason": "worker_timeout",
            "error_code": "worker_timeout",
            "error_message": f"OpenCode runner exceeded {timeout_seconds} seconds.",
            **metadata,
        }
    if state["error_code"] == "worker_timeout":
        return {
            "final_text": state["final_text"],
            "status": "timeout",
            "stop_reason": "worker_timeout",
            "error_code": "worker_timeout",
            "error_message": state["error_message"],
            **metadata,
        }
    if return_code != 0 or state["malformed_output"]:
        return {
            "final_text": state["final_text"],
            "status": "error",
            "stop_reason": "opencode_runner_exit",
            "error_code": state["error_code"] or return_code,
            "error_message": (
                state["error_message"]
                or f"OpenCode runner exited nonzero ({return_code}); see {stderr_path}"
            ),
            **metadata,
        }
    return {
        "final_text": state["final_text"],
        "status": "completed",
        "stop_reason": "final_message",
        "error_code": None,
        "error_message": None,
        **metadata,
    }


def _handle_runner_line(
    raw_line: str,
    *,
    events_stream: Any,
    progress_callback: Callable[..., None] | None,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        state["malformed_output"] = True
        state["error_code"] = state["error_code"] or "malformed_runner_output"
        state["error_message"] = (
            state["error_message"] or "OpenCode runner emitted malformed non-JSON output."
        )
        sanitized = {"event": "malformed_runner_output", "line_characters": len(line)}
        events_stream.write(json.dumps(sanitized, sort_keys=True) + "\n")
        events_stream.flush()
        return None
    if not isinstance(event, dict):
        state["malformed_output"] = True
        return None
    events_stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    events_stream.flush()
    name = event.get("event")
    if name == "runtime_verified":
        state["runtime_version"] = str(event.get("version") or "")
    elif name == "runtime_process_started":
        pid = event.get("pid")
        state["runtime_process_pid"] = pid if isinstance(pid, int) else None
    elif name == "thread_started":
        state["thread_id"] = str(event.get("thread_id") or "")
        state["session_id"] = str(event.get("session_id") or "")
    elif name in {"agent_message", "turn_complete"}:
        text = str(event.get("final_text") or event.get("text") or "")
        if text:
            state["final_text"] = text
    elif name == "error":
        state["error_code"] = str(event.get("error_code") or "")
        state["error_message"] = str(event.get("error_message") or "")

    if progress_callback is not None:
        if name == "thread_started":
            progress_callback(
                "opencode_session_started",
                thread_id=event.get("thread_id"),
                session_id=event.get("session_id"),
                model=event.get("model"),
            )
        elif name == "turn_started":
            progress_callback("worker_turn_started", backend="opencode")
        elif name == "tool_begin":
            progress_callback(
                "worker_tool_started",
                tool=event.get("tool"),
                call_id=event.get("call_id"),
            )
        elif name == "tool_end":
            progress_callback(
                "worker_tool_completed",
                tool=event.get("tool"),
                call_id=event.get("call_id"),
                status=event.get("status"),
            )
        elif name == "turn_complete":
            progress_callback("worker_turn_completed", response_status="completed")
        elif name == "error":
            progress_callback(
                "worker_error",
                error_code=event.get("error_code"),
                error_message=event.get("error_message"),
            )
    return event

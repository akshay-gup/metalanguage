"""Python wrapper for the Metalanguage-owned Codex runner."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_CRATE_DIR = PROJECT_ROOT / "crates" / "metalanguage-codex-runner"
RUNNER_MANIFEST = RUNNER_CRATE_DIR / "Cargo.toml"
ProgressCallback = Callable[[str, Any], None]
TokenUsageCallback = Callable[[dict[str, int], int], None]


def runner_binary_path(*, release: bool = False) -> Path:
    profile = "release" if release else "debug"
    return RUNNER_CRATE_DIR / "target" / profile / "metalanguage-codex-runner"


def ensure_codex_runner_built(*, release: bool = False) -> Path:
    cmd = ["cargo", "build", "--manifest-path", str(RUNNER_MANIFEST)]
    if release:
        cmd.append("--release")
    subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    return runner_binary_path(release=release)


def _codex_runner_source_inputs() -> list[Path]:
    inputs = [RUNNER_MANIFEST]
    lockfile = RUNNER_CRATE_DIR / "Cargo.lock"
    if lockfile.exists():
        inputs.append(lockfile)
    build_rs = RUNNER_CRATE_DIR / "build.rs"
    if build_rs.exists():
        inputs.append(build_rs)
    src_dir = RUNNER_CRATE_DIR / "src"
    if src_dir.exists():
        inputs.extend(sorted(src_dir.rglob("*.rs")))
    return inputs


def _newest_codex_runner_source_input() -> tuple[Path, int] | None:
    newest: tuple[Path, int] | None = None
    for path in _codex_runner_source_inputs():
        try:
            mtime_ns = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
        if newest is None or mtime_ns > newest[1]:
            newest = (path, mtime_ns)
    return newest


def _assert_managed_codex_runner_fresh(path: Path, *, release: bool = False) -> None:
    managed_path = runner_binary_path(release=release).expanduser().resolve()
    if path != managed_path:
        return

    newest = _newest_codex_runner_source_input()
    if newest is None:
        return
    newest_path, newest_mtime_ns = newest
    if path.stat().st_mtime_ns >= newest_mtime_ns:
        return

    raise RuntimeError(
        "Codex runner binary is older than its source inputs: "
        f"{path} is older than {newest_path}. Rebuild it with "
        f"`cargo build --manifest-path {RUNNER_MANIFEST}` "
        "or pass --codex-build-runner."
    )


def resolve_codex_runner_bin(
    runner_bin: Path | None,
    *,
    release: bool = False,
    build: bool = False,
) -> Path:
    if build:
        return ensure_codex_runner_built(release=release)

    path = runner_bin if runner_bin is not None else runner_binary_path(release=release)
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(
            "Codex runner binary does not exist: "
            f"{path}. Build it separately with "
            f"`cargo build --manifest-path {RUNNER_MANIFEST}` "
            "or pass --codex-build-runner."
        )
    _assert_managed_codex_runner_fresh(path, release=release)
    return path


def _prepare_rollout_env(
    *,
    workdir: Path,
    worker_state_dir: Path,
    codex_home: Path,
    rollout_username: str | None,
) -> dict[str, str]:
    env = os.environ.copy()
    worker_home = worker_state_dir / "home"
    worker_cache = worker_home / ".cache"
    worker_tmp = worker_home / "tmp"
    worker_hf_home = worker_cache / "huggingface"
    worker_hf_datasets = worker_cache / "huggingface_datasets"
    for path in [worker_home, worker_cache, worker_tmp, worker_hf_home, worker_hf_datasets]:
        path.mkdir(parents=True, exist_ok=True)

    git_identity = rollout_username or workdir.name
    env["CODEX_HOME"] = str(codex_home)
    env["HOME"] = str(worker_home)
    env["XDG_CACHE_HOME"] = str(worker_cache)
    env["HF_HOME"] = str(worker_hf_home)
    env["HF_DATASETS_CACHE"] = str(worker_hf_datasets)
    env["TMPDIR"] = str(worker_tmp)
    env.setdefault("GIT_AUTHOR_NAME", git_identity)
    env.setdefault("GIT_COMMITTER_NAME", git_identity)
    env.setdefault("GIT_AUTHOR_EMAIL", f"{git_identity}@local")
    env.setdefault("GIT_COMMITTER_EMAIL", f"{git_identity}@local")
    return env


def _terminate_runner_process(proc: subprocess.Popen[str], *, kill: bool) -> None:
    if proc.poll() is not None:
        return
    sig = signal.SIGKILL if kill else signal.SIGTERM
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        if kill:
            proc.kill()
        else:
            proc.terminate()


def _resolve_git_dir(worktree: Path) -> Path | None:
    dot_git = worktree / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    if not dot_git.is_file():
        return None

    try:
        contents = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "gitdir:"
    if not contents.startswith(prefix):
        return None

    git_dir = Path(contents[len(prefix) :].strip())
    if not git_dir.is_absolute():
        git_dir = dot_git.parent / git_dir
    return git_dir.resolve()


def _append_unique_path(paths: list[str], path: Path | None) -> None:
    if path is None:
        return
    resolved = str(path)
    if resolved not in paths:
        paths.append(resolved)


def run_codex_rollout(
    *,
    runner_bin: Path,
    model: str,
    workdir: Path,
    control_dir: Path,
    worker_state_dir: Path,
    codex_home: Path,
    seed_output_dir: Path,
    archive_repo_dir: Path,
    archive_git_dir: Path | None,
    shared_workspace_dir: Path,
    rollout_username: str | None,
    timeout_seconds: int,
    sandbox_mode: str = "workspace-write",
    initial_user_text: str = "Read README.md.",
    base_instructions: str | None = None,
    rollout_token_budget_tokens: int | None = None,
    instance_uuid: str | None = None,
    spawn_child_handler_context_path: Path | None = None,
    token_usage_callback: TokenUsageCallback | None = None,
    stop_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    runner_bin = runner_bin.expanduser().resolve()
    if not runner_bin.exists():
        raise FileNotFoundError(f"Codex runner binary does not exist: {runner_bin}")

    workspace_roots = [
        str(workdir),
        str(seed_output_dir),
        str(archive_repo_dir),
        str(shared_workspace_dir),
        str(worker_state_dir),
    ]
    additional_writable_roots = [
        str(seed_output_dir),
        str(archive_repo_dir),
        str(shared_workspace_dir),
        str(worker_state_dir),
    ]
    # Linked archive worktrees write their index through the per-worktree
    # gitdir and objects/refs through the persistent repository's common .git.
    _append_unique_path(additional_writable_roots, _resolve_git_dir(archive_repo_dir))
    _append_unique_path(additional_writable_roots, archive_git_dir)

    request = {
        "model": model,
        "cwd": str(workdir),
        "codex_home": str(codex_home),
        "initial_user_text": initial_user_text,
        "timeout_seconds": timeout_seconds,
        "sandbox_mode": sandbox_mode,
        "workspace_roots": workspace_roots,
        "additional_writable_roots": additional_writable_roots,
    }
    if rollout_token_budget_tokens is not None:
        request["rollout_token_budget_tokens"] = rollout_token_budget_tokens
    if instance_uuid is not None:
        request["instance_uuid"] = instance_uuid
    if spawn_child_handler_context_path is not None:
        request["spawn_child_handler_command"] = [
            sys.executable,
            str(PROJECT_ROOT / "main_loop.py"),
            "--child-tool-handler",
            str(spawn_child_handler_context_path),
        ]
    if base_instructions is not None and base_instructions.strip():
        request["base_instructions"] = base_instructions
    control_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(control_dir, 0o700)
    request_path = control_dir / "codex_runner.request.json"
    stderr_path = control_dir / "codex_runner.stderr.log"
    stdout_events_path = control_dir / "codex_runner.events.jsonl"
    final_text = ""
    thread_id: str | None = None
    session_id: str | None = None
    started_at = time.monotonic()
    state = {
        "final_text": "",
        "thread_id": "",
        "session_id": "",
        "error_code": "",
        "error_message": "",
        "tokens_spent": 0,
        "tokens_reserved_for_children": 0,
        "tokens_transferred_in": 0,
        "tokens_transferred_out": 0,
        "effective_rollout_token_budget_tokens": rollout_token_budget_tokens,
        "codex_total_tokens_seen": 0,
        "budget_exhausted": False,
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(request_path, 0o600)

    def _stop_requested() -> bool:
        return stop_requested is not None and stop_requested()

    env = _prepare_rollout_env(
        workdir=workdir,
        worker_state_dir=worker_state_dir,
        codex_home=codex_home,
        rollout_username=rollout_username,
    )
    with stderr_path.open("w", encoding="utf-8") as stderr_fh, stdout_events_path.open(
        "w",
        encoding="utf-8",
    ) as events_fh:
        os.chmod(stderr_path, 0o600)
        os.chmod(stdout_events_path, 0o600)
        proc = subprocess.Popen(
            [str(runner_bin)],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_fh,
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=True,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(request))
        proc.stdin.close()

        deadline = started_at + timeout_seconds + 15
        timed_out = False
        budget_exhausted = False
        cancelled = False
        cancel_reason: str | None = None
        while True:
            if proc.poll() is not None:
                remaining = proc.stdout.read()
                if remaining:
                    for raw_line in remaining.splitlines():
                        event = _handle_runner_line(
                            raw_line,
                            events_fh=events_fh,
                            progress_callback=progress_callback,
                            state=state,
                            rollout_token_budget_tokens=rollout_token_budget_tokens,
                            token_usage_callback=token_usage_callback,
                        )
                        if isinstance(event, dict) and event.get("event") == "thread_started":
                            thread_id = str(event.get("thread_id") or "") or thread_id
                            session_id = str(event.get("session_id") or "") or session_id
                        elif isinstance(event, dict) and event.get("event") == "turn_complete":
                            final_text = str(event.get("final_text") or "")
                        if state.get("budget_exhausted"):
                            budget_exhausted = True
                break
            if _stop_requested():
                cancelled = True
                cancel_reason = "child_slots_full"
                if progress_callback is not None:
                    progress_callback("worker_cancel_requested", reason=cancel_reason)
                _terminate_runner_process(proc, kill=False)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _terminate_runner_process(proc, kill=True)
                    proc.wait()
                remaining = proc.stdout.read()
                if remaining:
                    for raw_line in remaining.splitlines():
                        _handle_runner_line(
                            raw_line,
                            events_fh=events_fh,
                            progress_callback=progress_callback,
                            state=state,
                            rollout_token_budget_tokens=rollout_token_budget_tokens,
                            token_usage_callback=token_usage_callback,
                        )
                break
            if time.monotonic() > deadline:
                timed_out = True
                _terminate_runner_process(proc, kill=True)
                proc.wait()
                remaining = proc.stdout.read()
                if remaining:
                    for raw_line in remaining.splitlines():
                        _handle_runner_line(
                            raw_line,
                            events_fh=events_fh,
                            progress_callback=progress_callback,
                            state=state,
                            rollout_token_budget_tokens=rollout_token_budget_tokens,
                            token_usage_callback=token_usage_callback,
                        )
                break

            ready, _, _ = select.select([proc.stdout], [], [], 0.5)
            if not ready:
                continue
            raw_line = proc.stdout.readline()
            if not raw_line:
                continue
            event = _handle_runner_line(
                raw_line,
                events_fh=events_fh,
                progress_callback=progress_callback,
                state=state,
                rollout_token_budget_tokens=rollout_token_budget_tokens,
                token_usage_callback=token_usage_callback,
            )
            if isinstance(event, dict):
                if event.get("event") == "thread_started":
                    thread_id = str(event.get("thread_id") or "") or thread_id
                    session_id = str(event.get("session_id") or "") or session_id
                elif event.get("event") == "turn_complete":
                    final_text = str(event.get("final_text") or "")
            if state.get("budget_exhausted"):
                budget_exhausted = True

        return_code = proc.wait()
    thread_id = thread_id or state.get("thread_id") or None
    session_id = session_id or state.get("session_id") or None
    final_text = final_text or state.get("final_text", "")

    tokens_spent = int(state.get("tokens_spent") or 0)
    tokens_reserved_for_children = int(state.get("tokens_reserved_for_children") or 0)
    tokens_transferred_in = int(state.get("tokens_transferred_in") or 0)
    tokens_transferred_out = int(state.get("tokens_transferred_out") or 0)
    effective_budget = state.get("effective_rollout_token_budget_tokens")
    charged_tokens = tokens_spent + tokens_reserved_for_children + tokens_transferred_out
    if cancelled:
        return {
            "final_text": final_text,
            "status": "cancelled",
            "stop_reason": cancel_reason or "cancelled",
            "error_code": cancel_reason or "cancelled",
            "error_message": "Codex rollout stopped because the child slot cap is full.",
            "thread_id": thread_id,
            "session_id": session_id,
            "tokens_spent": tokens_spent,
            "tokens_reserved_for_children": tokens_reserved_for_children,
            "tokens_transferred_in": tokens_transferred_in,
            "tokens_transferred_out": tokens_transferred_out,
            "rollout_token_budget_tokens": rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": effective_budget,
            "request_path": str(request_path),
            "stderr_path": str(stderr_path),
            "events_path": str(stdout_events_path),
        }
    if budget_exhausted:
        return {
            "final_text": final_text,
            "status": "budget_exhausted",
            "stop_reason": "token_budget_exhausted",
            "error_code": "token_budget_exhausted",
            "error_message": f"Token budget exhausted: {charged_tokens}/{effective_budget}.",
            "thread_id": thread_id,
            "session_id": session_id,
            "tokens_spent": tokens_spent,
            "tokens_reserved_for_children": tokens_reserved_for_children,
            "tokens_transferred_in": tokens_transferred_in,
            "tokens_transferred_out": tokens_transferred_out,
            "rollout_token_budget_tokens": rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": effective_budget,
            "request_path": str(request_path),
            "stderr_path": str(stderr_path),
            "events_path": str(stdout_events_path),
        }
    if timed_out:
        return {
            "final_text": final_text,
            "status": "timeout",
            "stop_reason": "worker_timeout",
            "error_code": "worker_timeout",
            "error_message": f"Codex runner exceeded {timeout_seconds} seconds.",
            "thread_id": thread_id,
            "session_id": session_id,
            "tokens_spent": tokens_spent,
            "tokens_reserved_for_children": tokens_reserved_for_children,
            "tokens_transferred_in": tokens_transferred_in,
            "tokens_transferred_out": tokens_transferred_out,
            "rollout_token_budget_tokens": rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": effective_budget,
            "request_path": str(request_path),
            "stderr_path": str(stderr_path),
            "events_path": str(stdout_events_path),
        }
    if rollout_token_budget_tokens is not None and tokens_spent <= 0:
        return {
            "final_text": final_text,
            "status": "budget_tracking_error",
            "stop_reason": "missing_token_usage",
            "error_code": "missing_token_usage",
            "error_message": "Codex runner did not emit token usage for budget enforcement.",
            "thread_id": thread_id,
            "session_id": session_id,
            "tokens_spent": tokens_spent,
            "tokens_reserved_for_children": tokens_reserved_for_children,
            "tokens_transferred_in": tokens_transferred_in,
            "tokens_transferred_out": tokens_transferred_out,
            "rollout_token_budget_tokens": rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": effective_budget,
            "request_path": str(request_path),
            "stderr_path": str(stderr_path),
            "events_path": str(stdout_events_path),
        }
    if return_code != 0:
        runner_error = state.get("error_message") or f"Codex runner exited nonzero ({return_code})"
        return {
            "final_text": final_text,
            "status": "error",
            "stop_reason": "codex_runner_exit",
            "error_code": state.get("error_code") or return_code,
            "error_message": f"{runner_error}; see {stderr_path}",
            "thread_id": thread_id,
            "session_id": session_id,
            "tokens_spent": tokens_spent,
            "tokens_reserved_for_children": tokens_reserved_for_children,
            "tokens_transferred_in": tokens_transferred_in,
            "tokens_transferred_out": tokens_transferred_out,
            "rollout_token_budget_tokens": rollout_token_budget_tokens,
            "effective_rollout_token_budget_tokens": effective_budget,
            "request_path": str(request_path),
            "stderr_path": str(stderr_path),
            "events_path": str(stdout_events_path),
        }
    return {
        "final_text": final_text,
        "status": "completed",
        "stop_reason": "final_message",
        "error_code": None,
        "error_message": None,
        "thread_id": thread_id,
        "session_id": session_id,
        "tokens_spent": tokens_spent,
        "tokens_reserved_for_children": tokens_reserved_for_children,
        "tokens_transferred_in": tokens_transferred_in,
        "tokens_transferred_out": tokens_transferred_out,
        "rollout_token_budget_tokens": rollout_token_budget_tokens,
        "effective_rollout_token_budget_tokens": effective_budget,
        "request_path": str(request_path),
        "stderr_path": str(stderr_path),
        "events_path": str(stdout_events_path),
    }


def _handle_runner_line(
    raw_line: str,
    *,
    events_fh: Any,
    progress_callback: Callable[..., None] | None,
    state: dict[str, Any],
    rollout_token_budget_tokens: int | None,
    token_usage_callback: TokenUsageCallback | None,
) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None
    events_fh.write(line + "\n")
    events_fh.flush()
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        if progress_callback is not None:
            progress_callback("codex_runner_stdout", line=line[:1000])
        return None

    if not isinstance(event, dict):
        return None
    name = event.get("event")
    token_usage = _record_codex_token_usage(
        event,
        state=state,
        token_usage_callback=token_usage_callback,
    )
    if name == "thread_started":
        state["thread_id"] = str(event.get("thread_id") or "")
        state["session_id"] = str(event.get("session_id") or "")
    elif name in {"token_usage", "tool_end"}:
        reserved = _token_int(event.get("tokens_reserved_for_children"))
        if reserved > int(state.get("tokens_reserved_for_children") or 0):
            state["tokens_reserved_for_children"] = reserved
        transferred_in = _token_int(event.get("tokens_transferred_in"))
        if transferred_in > int(state.get("tokens_transferred_in") or 0):
            state["tokens_transferred_in"] = transferred_in
        transferred_out = _token_int(event.get("tokens_transferred_out"))
        if transferred_out > int(state.get("tokens_transferred_out") or 0):
            state["tokens_transferred_out"] = transferred_out
        effective_budget = _token_int(event.get("effective_rollout_token_budget_tokens"))
        if effective_budget > 0:
            state["effective_rollout_token_budget_tokens"] = effective_budget
    elif name in {"agent_message", "turn_complete"}:
        text = str(event.get("final_text") or event.get("text") or "")
        if text:
            state["final_text"] = text
    elif name == "error":
        reserved = _token_int(event.get("tokens_reserved_for_children"))
        if reserved > int(state.get("tokens_reserved_for_children") or 0):
            state["tokens_reserved_for_children"] = reserved
        transferred_in = _token_int(event.get("tokens_transferred_in"))
        if transferred_in > int(state.get("tokens_transferred_in") or 0):
            state["tokens_transferred_in"] = transferred_in
        transferred_out = _token_int(event.get("tokens_transferred_out"))
        if transferred_out > int(state.get("tokens_transferred_out") or 0):
            state["tokens_transferred_out"] = transferred_out
        effective_budget = _token_int(event.get("effective_rollout_token_budget_tokens"))
        if effective_budget > 0:
            state["effective_rollout_token_budget_tokens"] = effective_budget
        state["error_code"] = str(event.get("error_code") or "")
        state["error_message"] = str(event.get("error_message") or "")
        if state["error_code"] == "token_budget_exhausted":
            event_tokens_spent = _token_int(event.get("tokens_spent"))
            if event_tokens_spent > int(state.get("tokens_spent") or 0):
                state["tokens_spent"] = event_tokens_spent
            state["budget_exhausted"] = True

    if progress_callback is not None:
        if name == "thread_started":
            progress_callback(
                "codex_thread_started",
                thread_id=event.get("thread_id"),
                session_id=event.get("session_id"),
                model=event.get("model"),
            )
        elif name == "turn_started":
            progress_callback(
                "worker_turn_started",
                turn_id=event.get("turn_id"),
                model_context_window=event.get("model_context_window"),
            )
        elif name == "tool_begin":
            progress_callback(
                "worker_tool_started",
                tool=event.get("tool"),
                call_id=event.get("call_id"),
                command=event.get("command"),
            )
        elif name == "tool_end":
            progress_callback(
                "worker_tool_completed",
                tool=event.get("tool"),
                call_id=event.get("call_id"),
                exit_code=event.get("exit_code"),
                status=event.get("status"),
            )
        elif name == "turn_complete":
            progress_callback(
                "worker_turn_completed",
                turn_id=event.get("turn_id"),
                tool_call_count=None,
                response_status="completed",
            )
        elif name == "token_usage" and token_usage is not None:
            progress_callback(
                "worker_token_usage",
                token_usage=token_usage,
                tokens_spent=state.get("tokens_spent"),
                tokens_reserved_for_children=state.get("tokens_reserved_for_children"),
                tokens_transferred_in=state.get("tokens_transferred_in"),
                tokens_transferred_out=state.get("tokens_transferred_out"),
                rollout_token_budget_tokens=rollout_token_budget_tokens,
            )
        elif name == "error":
            progress_callback(
                "worker_error",
                error_code=event.get("error_code"),
                error_message=event.get("error_message"),
            )
    return event


def _record_codex_token_usage(
    event: dict[str, Any],
    *,
    state: dict[str, Any],
    token_usage_callback: TokenUsageCallback | None,
) -> dict[str, int] | None:
    if event.get("event") != "token_usage":
        return None
    current_spent = int(state.get("tokens_spent") or 0)
    event_tokens_spent = _token_int(event.get("tokens_spent"))
    total_usage = event.get("total")
    if isinstance(total_usage, dict):
        total_seen = _token_int(total_usage.get("total_tokens"))
        previous_seen = int(state.get("codex_total_tokens_seen") or 0)
        if total_seen > 0 and total_seen <= previous_seen:
            if event_tokens_spent > current_spent:
                state["tokens_spent"] = event_tokens_spent
            return None
        if total_seen > 0:
            state["codex_total_tokens_seen"] = total_seen

    if event_tokens_spent > 0 and event_tokens_spent <= current_spent:
        return None

    usage = _codex_usage_fields(event.get("last"))
    if usage is None:
        if event_tokens_spent > current_spent:
            state["tokens_spent"] = event_tokens_spent
        return None
    tokens_spent = max(current_spent + usage["total_tokens"], event_tokens_spent)
    state["tokens_spent"] = tokens_spent
    if token_usage_callback is not None:
        token_usage_callback(usage, tokens_spent)
    return usage


def _codex_usage_fields(raw_usage: Any) -> dict[str, int] | None:
    if not isinstance(raw_usage, dict):
        return None
    usage = {
        "input_tokens": _token_int(raw_usage.get("input_tokens")),
        "cached_input_tokens": _token_int(raw_usage.get("cached_input_tokens")),
        "output_tokens": _token_int(raw_usage.get("output_tokens")),
        "reasoning_output_tokens": _token_int(raw_usage.get("reasoning_output_tokens")),
        "total_tokens": _token_int(raw_usage.get("total_tokens")),
    }
    if usage["total_tokens"] <= 0:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    if usage["total_tokens"] <= 0:
        return None
    if (
        usage["input_tokens"] <= 0
        and usage["output_tokens"] <= 0
        and usage["reasoning_output_tokens"] <= 0
    ):
        return None
    return usage


def _token_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

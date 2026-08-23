#!/usr/bin/env python3
"""Minimal RLVR episode loop.

Flow:
1) Sample one task from a Hugging Face RLVR-style dataset.
2) Create an ephemeral episode temp directory and write task metadata.
3) Run a tool-using worker (LLM + bash function tool) in that directory.
4) Collect benchmark outcomes through the selected benchmark driver.
5) Append run metadata to a growing JSONL log.
6) Print a one-line summary.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.arc_agi_benchmark import ArcAgiBenchmarkDriver, ArcAgiConfig
from utils.benchmark_events import new_instance_uuid
from utils.benchmark_driver import (
    BenchmarkDriver,
    BenchmarkItemRef,
    BenchmarkOutcome,
    RolloutBenchmark,
    ScheduledBenchmarkBatch,
    active_benchmark_item,
)
from utils.codex_runner import resolve_codex_runner_bin, run_codex_rollout
from utils.opencode_runner import (
    SOURCE_AUDITED_BUN_VERSIONS,
    SOURCE_AUDITED_OPENCODE_VERSIONS,
    executable_version,
    file_sha256,
    custom_provider_configuration,
    custom_provider_environment_names,
    custom_provider_fingerprint,
    opencode_python_fingerprint,
    opencode_worker_fingerprint,
    prepare_provider_environment,
    provider_environment_fingerprint,
    provider_environment_names,
    resolve_bubblewrap_bin,
    resolve_bun_bin,
    resolve_opencode_bin,
    resolve_opencode_worker_script,
    run_opencode_rollout,
    text_sha256,
    validate_opencode_host_primitives,
)
from utils.openrouter import (
    OpenRouterAPIError,
    bash_tool,
    call_openrouter_with_tools,
    get_tool_calls,
    spawn_child_tool,
)
from utils.open_ended_benchmark import (
    OpenEndedBenchmarkDriver,
    OpenEndedConfig,
    OpenEndedTask,
    resolve_open_ended_task,
)
from utils.supergpqa_benchmark import SuperGpqaBenchmarkDriver, SuperGpqaConfig


@dataclass
class RolloutResult:
    rollout_index: int
    record: dict[str, Any]
    successful_dir: Path | None
    summary: str
    error: str | None = None
    benchmark_outcome: BenchmarkOutcome | None = None


@dataclass
class ArchiveWorktree:
    path: Path
    branch: str
    base_commit: str


@dataclass
class WorkerResult:
    final_text: str
    status: str
    stop_reason: str | None = None
    error_code: str | int | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


CONTINUATION_CONTEXT_FILENAME = "continuation_context.json"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_MODEL = "moonshotai/kimi-k2.6"
DEFAULT_NUM_ROLLOUTS = 8
DEFAULT_WORKER_TIMEOUT_SECONDS = 3600
DEFAULT_BASH_TIMEOUT_SECONDS = 120
DEFAULT_OPENROUTER_MAX_RETRIES = 5
DEFAULT_RUNTIME_ROOT = Path.home() / "Documents" / "metalanguage_runs"
DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
BUNDLED_BOOTSTRAP_SEED_DIR = PROJECT_ROOT / "seeds" / "bootstrap"
RUNTIME_BENCHMARK_IDENTITY_FILENAME = "runtime_benchmark.json"
STABLE_SEED_FILENAMES = ("README.md",)
READ_README_TASK_INSTRUCTIONS = (
    "This rollout has no assigned task. README.md describes its environment."
)
CODEX_READ_README_BASE_INSTRUCTIONS = READ_README_TASK_INSTRUCTIONS
BENCHMARK_README_FILENAME = "BENCHMARK.md"


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(env_path: Path = DEFAULT_ENV_PATH) -> None:
    """Load simple KEY=VALUE lines from .env without overriding real environment."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_env_quotes(value))


def _normalize_difficulty_filter(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    values = tuple(value.strip().lower() for value in raw.split(",") if value.strip())
    if not values or values in {("all",), ("any",)}:
        return None
    if any(value in {"all", "any"} for value in values):
        raise ValueError("--difficulty-filter cannot mix all/any with specific values")
    return values


def _format_bootstrap_seed_prompt(seed_dir: Path) -> str:
    for filename in STABLE_SEED_FILENAMES:
        path = seed_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Bootstrap seed is missing required stable file: {path}")
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Bootstrap seed stable file is empty: {path}")

    return READ_README_TASK_INSTRUCTIONS


def _extract_text_from_response(response_json: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response_json.get("output", []):
        if item.get("type") != "message":
            continue
        for chunk in item.get("content", []):
            if not isinstance(chunk, dict):
                continue
            if chunk.get("type") in {"output_text", "text"} and chunk.get("text"):
                parts.append(str(chunk["text"]))
    return "\n".join(parts).strip()


def _run_bash_tool(
    command: str,
    working_directory: str,
    *,
    worker_state_dir: Path,
    timeout_seconds: int,
    rollout_username: str | None = None,
) -> dict[str, Any]:
    try:
        git_identity = rollout_username or Path(working_directory).name
        env = os.environ.copy()
        worker_home = worker_state_dir / "home"
        worker_cache = worker_home / ".cache"
        worker_tmp = worker_home / "tmp"
        worker_hf_home = worker_cache / "huggingface"
        worker_hf_datasets = worker_cache / "huggingface_datasets"
        for path in [worker_home, worker_cache, worker_tmp, worker_hf_home, worker_hf_datasets]:
            path.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(worker_home)
        env["XDG_CACHE_HOME"] = str(worker_cache)
        env["HF_HOME"] = str(worker_hf_home)
        env["HF_DATASETS_CACHE"] = str(worker_hf_datasets)
        env["TMPDIR"] = str(worker_tmp)
        env.setdefault("GIT_AUTHOR_NAME", git_identity)
        env.setdefault("GIT_COMMITTER_NAME", git_identity)
        env.setdefault("GIT_AUTHOR_EMAIL", f"{git_identity}@local")
        env.setdefault("GIT_COMMITTER_EMAIL", f"{git_identity}@local")
        proc = subprocess.run(
            command,
            shell=True,
            cwd=working_directory,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nCommand timed out after {timeout_seconds} seconds.",
            "timed_out": True,
        }


def _run_git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _sanitize_for_path(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return safe or "unknown_task"


def _replace_with_symlink(link_path: Path, target_path: Path) -> None:
    if link_path.is_symlink() or link_path.is_file():
        link_path.unlink()
    elif link_path.exists():
        shutil.rmtree(link_path)
    link_path.symlink_to(target_path, target_is_directory=target_path.is_dir())


def _format_runtime_markdown(
    *,
    instance_uuid: str,
    child_slot_index: int | None = None,
    problem_pool_json_path: str | None = None,
    problem_pool_markdown_path: str | None = None,
    configured_problem_pool_size: int | None = None,
    problem_pool_count: int | None = None,
    live_peer_instances: list[dict[str, Any]] | None = None,
    parent_instance_uuid: str | None = None,
    has_problem_pool: bool = True,
) -> str:
    lines = [
        "# Runtime",
        "",
        "## Paths",
        "",
        "- seed_output: seed_output/",
        "- archive: archive/",
        "- shared_workspace: shared_workspace/",
    ]
    if has_problem_pool:
        lines.extend(
            [
                f"- problem_pool_json: {problem_pool_json_path or ''}",
                f"- problem_pool_markdown: {problem_pool_markdown_path or ''}",
            ]
        )
    else:
        lines.append("- task: shared_workspace/BENCHMARK.md")
    lines.extend(
        [
            "",
            "## Runtime Values",
            "",
            f"- instance_uuid: {instance_uuid}",
            f"- parent_instance_uuid: {parent_instance_uuid or ''}",
            f"- reserved_child_slot_index: {child_slot_index if child_slot_index is not None else ''}",
            "- successful_child_limit: 1",
        ]
    )
    if has_problem_pool:
        lines.extend(
            [
                f"- configured_problem_pool_size: {configured_problem_pool_size if configured_problem_pool_size is not None else 'uncapped'}",
                f"- problem_pool_count: {problem_pool_count if problem_pool_count is not None else ''}",
                "",
                "## Benchmark Pool Semantics",
                "",
                (
                    "- this pool copy is a deterministic sampled working set of currently eligible benchmark items; it may not contain every eligible item;"
                    if configured_problem_pool_size is not None
                    else "- this pool copy contains all currently eligible benchmark items;"
                ),
                "- each benchmark item appears at most once in this pool copy;",
                "- items not completed under the benchmark's official policy may reappear later;",
                "- officially completed items may leave future pools after batch finalization;",
                "- same-batch rollouts share this pool and may independently interact with the same item; scoring policy is benchmark-specific.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Evaluation",
                "",
                "- evaluation: unconfigured",
                "- this profile has no evaluator, score, reward, solved status, or ranking.",
            ]
        )
    if live_peer_instances:
        lines.extend(["", "## Live Peer Instances", ""])
        for peer in live_peer_instances:
            lines.append(
                "- "
                f"rollout_index={peer.get('rollout_index')} "
                f"rollout_username={peer.get('rollout_username')} "
                f"instance_uuid={peer.get('instance_uuid')}"
            )
    return "\n".join(lines) + "\n"


def _parse_spawn_child_arguments(args: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    unexpected = sorted(set(args) - {"prompt", "workspace_dir"})
    if unexpected:
        return None, None, f"spawn_child received unsupported arguments: {', '.join(unexpected)}"
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None, None, "spawn_child requires a non-empty string prompt"

    raw_workspace_dir = args.get("workspace_dir")
    if not isinstance(raw_workspace_dir, str) or not raw_workspace_dir.strip():
        return None, None, "spawn_child requires a non-empty workspace_dir"
    workspace_dir = raw_workspace_dir.strip()

    return prompt, workspace_dir, None


def _resolve_spawn_workspace_dir(context: dict[str, Any], workspace_dir: str | None) -> tuple[Path | None, str | None]:
    if workspace_dir is None:
        return None, "spawn_child requires a workspace_dir containing README.md"
    workdir = Path(str(context["workdir"])).resolve()
    raw_path = Path(workspace_dir).expanduser()
    candidate = raw_path.resolve() if raw_path.is_absolute() else (workdir / raw_path).resolve()
    if candidate == workdir or not _is_within(candidate, workdir):
        return None, "workspace_dir must be a workspace-local directory, not the rollout workspace root"
    if not candidate.is_dir():
        return None, f"workspace_dir is not a directory: {workspace_dir}"
    readme = candidate / "README.md"
    if readme.is_symlink() or not readme.is_file():
        return None, "workspace_dir must contain a regular README.md at its root"
    try:
        readme_text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, "workspace_dir/README.md must be readable UTF-8 text"
    if not readme_text.strip():
        return None, "workspace_dir/README.md must contain non-blank text"
    return candidate, None


def _write_continuation_context(
    context: dict[str, Any], control_dir: Path
) -> Path:
    control_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(control_dir, 0o700)
    context_path = control_dir / CONTINUATION_CONTEXT_FILENAME
    temp_path = context_path.with_suffix(context_path.suffix + f".{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, context_path)
    os.chmod(context_path, 0o600)
    return context_path


def _make_continuation_context(
    *,
    worker_backend: str,
    model: str,
    workdir: Path,
    seed_output_dir: Path,
    archive_repo_dir: Path,
    shared_workspace_dir: Path,
    shared_workspace_write_log: Path,
    spawn_slots_path: Path,
    spawn_slots_dir: Path,
    live_peer_instances: list[dict[str, Any]],
    progress_log_path: Path,
    population_size: int,
    generation: int,
    seed: int,
    task_index: int,
    task_id: str,
    rollout_index: int,
    rollout_username: str,
    instance_uuid: str,
    worker_timeout_seconds: int,
    bash_timeout_seconds: int,
    openrouter_max_retries: int,
    codex_runner_bin: Path | None,
    codex_home: Path,
    codex_sandbox_mode: str,
    codex_initial_prompt: str,
    codex_base_instructions: str | None,
    parent_instance_uuid: str | None = None,
) -> dict[str, Any]:
    return {
        "worker_backend": worker_backend,
        "model": model,
        "workdir": str(workdir),
        "seed_output_dir": str(seed_output_dir),
        "archive_repo_dir": str(archive_repo_dir),
        "shared_workspace_dir": str(shared_workspace_dir),
        "shared_workspace_write_log": str(shared_workspace_write_log),
        "spawn_slots_path": str(spawn_slots_path),
        "spawn_slots_dir": str(spawn_slots_dir),
        "population_size": population_size,
        "live_peer_instances": live_peer_instances,
        "progress_log": str(progress_log_path),
        "generation": generation,
        "seed": seed,
        "task_index": task_index,
        "task_id": task_id,
        "rollout_index": rollout_index,
        "rollout_username": rollout_username,
        "instance_uuid": instance_uuid,
        "parent_instance_uuid": parent_instance_uuid,
        "worker_timeout_seconds": worker_timeout_seconds,
        "bash_timeout_seconds": bash_timeout_seconds,
        "openrouter_max_retries": openrouter_max_retries,
        "codex_runner_bin": str(codex_runner_bin) if codex_runner_bin is not None else None,
        "codex_home": str(codex_home),
        "codex_sandbox_mode": codex_sandbox_mode,
        "codex_initial_prompt": codex_initial_prompt,
        "codex_base_instructions": codex_base_instructions,
    }


def _problem_assignment_key(context: dict[str, Any]) -> str:
    return ":".join(
        [
            f"generation={context.get('generation')}",
            f"seed={context.get('seed')}",
            f"task_index={context.get('task_index')}",
            f"rollout_index={context.get('rollout_index')}",
        ]
    )


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_file_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def _spawn_failure(
    error: str,
    *,
    error_code: str,
    retryable: bool,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "success": False,
        "child_spawned": False,
        "parent_continues": True,
        "retryable": retryable,
        "error_code": error_code,
        "error": error,
        **fields,
    }


def _slot_for_source_rollout(
    slots: list[dict[str, Any]],
    source_rollout_index: int,
) -> dict[str, Any] | None:
    for slot in slots:
        if _slot_source_rollout_index(slot) == source_rollout_index:
            return slot
    return None


def _slot_source_rollout_index(slot: dict[str, Any]) -> int | None:
    try:
        return int(slot.get("source_rollout_index"))
    except (TypeError, ValueError):
        return None


def _already_spawned_failure(
    *,
    source_rollout_index: int,
    slot: dict[str, Any],
    prompt_chars: int | None,
) -> dict[str, Any]:
    return _spawn_failure(
        "This rollout has already spawned its child; each rollout may successfully spawn at most one child.",
        error_code="child_already_spawned",
        retryable=False,
        source_rollout_index=source_rollout_index,
        slot_index=slot.get("slot_index", source_rollout_index),
        child_instance_uuid=slot.get("child_instance_uuid"),
        prompt_chars=prompt_chars,
    )


def _spawn_item_ref(context: dict[str, Any]) -> BenchmarkItemRef:
    ref = active_benchmark_item(context)
    if ref is not None:
        return ref
    task_id = str(context["task_id"])
    task_index = int(context["task_index"])
    return BenchmarkItemRef(
        item_id=task_id,
        source_id=task_id,
        item_index=task_index,
        iteration_index=task_index,
    )


def _record_spawned_child(
    *,
    context: dict[str, Any],
    child_instance_uuid: str,
    child_prompt: str,
    source_workspace_dir: Path,
) -> dict[str, Any]:
    slots_path = Path(str(context["spawn_slots_path"]))
    slots_dir = Path(str(context["spawn_slots_dir"]))
    item_ref = _spawn_item_ref(context)
    source_id = item_ref.source_id or item_ref.item_id
    source_item_id = item_ref.item_id
    source_item_index = item_ref.item_index
    source_rollout_index = int(context["rollout_index"])
    slot_index = source_rollout_index
    population_size = int(context["population_size"])
    lock_path = slots_path.with_suffix(slots_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    slots_dir.mkdir(parents=True, exist_ok=True)

    initial_state = _read_json_file(slots_path, {})
    initial_slots = initial_state.get("slots") if isinstance(initial_state, dict) else None
    if isinstance(initial_slots, list):
        existing_slot = _slot_for_source_rollout(initial_slots, source_rollout_index)
        if existing_slot is not None:
            return _already_spawned_failure(
                source_rollout_index=source_rollout_index,
                slot=existing_slot,
                prompt_chars=len(child_prompt),
            )

    slot_dir = slots_dir / f"slot_{slot_index:03d}_{child_instance_uuid[:8]}"
    child_workspace_dir = slot_dir / "workspace"
    try:
        slot_dir.mkdir(parents=True, exist_ok=False)
        child_workspace_dir.mkdir(parents=True, exist_ok=False)
        copy_seed_workspace(source_workspace_dir, child_workspace_dir)
        copied_readme = child_workspace_dir / "README.md"
        if copied_readme.is_symlink() or not copied_readme.is_file():
            raise RuntimeError("copied child workspace is missing a regular README.md")
        try:
            copied_readme_text = copied_readme.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("copied child README.md is not readable UTF-8 text") from exc
        if not copied_readme_text.strip():
            raise RuntimeError("copied child README.md contains no non-blank text")
    except BaseException:
        shutil.rmtree(slot_dir, ignore_errors=True)
        raise

    with lock_path.open("w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        state = _read_json_file(slots_path, {})
        slots = state.get("slots") if isinstance(state, dict) else None
        if not isinstance(slots, list):
            slots = []
        existing_slot = _slot_for_source_rollout(slots, source_rollout_index)
        if existing_slot is not None:
            shutil.rmtree(slot_dir, ignore_errors=True)
            return _already_spawned_failure(
                source_rollout_index=source_rollout_index,
                slot=existing_slot,
                prompt_chars=len(child_prompt),
            )
        manifest_path = slot_dir / "slot_manifest.json"
        metadata = {
            "child_instance_uuid": child_instance_uuid,
            "slot_index": slot_index,
            "parent_instance_uuid": context["instance_uuid"],
            "parent_rollout_username": context["rollout_username"],
            "prompt": child_prompt,
            "prompt_chars": len(child_prompt),
            "source_workspace_dir": str(source_workspace_dir),
            "workspace_dir": str(child_workspace_dir),
            "slot_dir": str(slot_dir),
            "manifest_path": str(manifest_path),
            "source_task_index": context["task_index"],
            "source_problem_task_index": source_item_index,
            "source_task_id": source_id,
            "source_problem_uid": source_item_id,
            "source_benchmark_item": item_ref.to_metadata(),
            "source_rollout_index": source_rollout_index,
            "population_size": population_size,
        }
        try:
            _write_json_file_atomic(manifest_path, metadata)
            slots.append(dict(metadata))
            slots.sort(
                key=lambda slot: (
                    _slot_source_rollout_index(slot) is None,
                    _slot_source_rollout_index(slot) or 0,
                )
            )
            _write_json_file_atomic(
                slots_path,
                {
                    "source_task_index": context["task_index"],
                    "source_task_id": source_id,
                    "source_problem_uid": source_item_id,
                    "source_benchmark_item": item_ref.to_metadata(),
                    "population_size": population_size,
                    "spawned_child_count": len(slots),
                    "slots": slots,
                },
            )
        except BaseException:
            shutil.rmtree(slot_dir, ignore_errors=True)
            raise
        return {
            "success": True,
            "child_spawned": True,
            "parent_continues": True,
            "retryable": False,
            "message": "Child spawned successfully; the parent rollout continues.",
            "source_rollout_index": source_rollout_index,
            "slot_index": slot_index,
            "child_instance_uuid": child_instance_uuid,
            "slot_dir": str(slot_dir),
            "workspace_dir": str(child_workspace_dir),
            "prompt_chars": len(child_prompt),
            "population_size": population_size,
        }


def _read_slot_manifest(slot: dict[str, Any]) -> dict[str, Any]:
    raw_manifest_path = slot.get("manifest_path")
    if not isinstance(raw_manifest_path, str) or not raw_manifest_path:
        raw_slot_dir = slot.get("slot_dir")
        if not isinstance(raw_slot_dir, str) or not raw_slot_dir:
            return {}
        raw_manifest_path = str(Path(raw_slot_dir) / "slot_manifest.json")
    manifest = _read_json_file(Path(raw_manifest_path), {})
    return manifest if isinstance(manifest, dict) else {}


def _slot_prompt(slot: dict[str, Any]) -> str | None:
    prompt = slot.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    manifest_prompt = _read_slot_manifest(slot).get("prompt")
    if isinstance(manifest_prompt, str) and manifest_prompt.strip():
        return manifest_prompt
    return None


def _slot_workspace_dir(slot: dict[str, Any]) -> Path | None:
    raw_workspace_dir = slot.get("workspace_dir")
    if not isinstance(raw_workspace_dir, str) or not raw_workspace_dir:
        raw_workspace_dir = _read_slot_manifest(slot).get("workspace_dir")
    if isinstance(raw_workspace_dir, str) and raw_workspace_dir:
        return Path(raw_workspace_dir)
    return None


def _slot_child_instance_uuid(slot: dict[str, Any]) -> str | None:
    child_instance_uuid = slot.get("child_instance_uuid")
    if not isinstance(child_instance_uuid, str) or not child_instance_uuid:
        child_instance_uuid = _read_slot_manifest(slot).get("child_instance_uuid")
    if isinstance(child_instance_uuid, str) and child_instance_uuid:
        return child_instance_uuid
    return None


def _load_spawned_child_slots(
    spawn_slots_path: Path,
    *,
    source_rollout_index: int | None = None,
) -> list[dict[str, Any]]:
    state = _read_json_file(spawn_slots_path, {})
    slots = state.get("slots") if isinstance(state, dict) else None
    if not isinstance(slots, list):
        return []
    sorted_slots = sorted(
        slots,
        key=lambda item: (
            _slot_source_rollout_index(item) is None,
            _slot_source_rollout_index(item) or 0,
        )
        if isinstance(item, dict)
        else (True, 0),
    )
    child_slots: list[dict[str, Any]] = []
    included_source_rollout_indices: set[int] = set()
    for slot in sorted_slots:
        if not isinstance(slot, dict):
            continue
        slot_source_rollout_index = _slot_source_rollout_index(slot)
        if slot_source_rollout_index is None:
            continue
        if slot_source_rollout_index in included_source_rollout_indices:
            continue
        if source_rollout_index is not None:
            if slot_source_rollout_index != source_rollout_index:
                continue
        if _slot_prompt(slot) is not None:
            child_slots.append(slot)
            included_source_rollout_indices.add(slot_source_rollout_index)
    return child_slots


def _load_spawned_child_parent_slots(spawn_slots_path: Path) -> list[dict[str, Any]]:
    return _load_spawned_child_slots(spawn_slots_path)


def _is_reinitialized_bootstrap_slot(slot: dict[str, Any] | None) -> bool:
    return bool(slot and slot.get("bootstrap_reinitialized") is True)


def _refill_parent_pool_with_bootstrap_slots(
    spawned_child_slots: list[dict[str, Any]],
    *,
    target_count: int,
) -> tuple[list[dict[str, Any]], int]:
    spawned_slots_by_index: dict[int, dict[str, Any]] = {}
    for slot in spawned_child_slots:
        source_rollout_index = _slot_source_rollout_index(slot)
        if source_rollout_index is None or not 0 <= source_rollout_index < target_count:
            continue
        spawned_slots_by_index.setdefault(source_rollout_index, slot)
    parent_pool: list[dict[str, Any]] = []
    for slot_index in range(target_count):
        spawned_slot = spawned_slots_by_index.get(slot_index)
        if spawned_slot is not None:
            parent_pool.append(spawned_slot)
            continue
        child_instance_uuid = new_instance_uuid()
        parent_pool.append(
            {
                "bootstrap_reinitialized": True,
                "child_instance_uuid": child_instance_uuid,
                "slot_index": slot_index,
                "parent_instance_uuid": None,
                "parent_rollout_username": None,
                "prompt": READ_README_TASK_INSTRUCTIONS,
                "prompt_chars": len(READ_README_TASK_INSTRUCTIONS),
                "workspace_dir": None,
                "slot_dir": None,
                "manifest_path": None,
            }
        )
    reinitialized_count = len(parent_pool) - len(spawned_slots_by_index)
    return parent_pool, reinitialized_count


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _resolve_runtime_root(value: str, *, create: bool = True) -> Path:
    documents_dir = (Path.home() / "Documents").resolve()
    raw_root = Path(value).expanduser()
    root = raw_root.resolve() if raw_root.is_absolute() else (documents_dir / raw_root).resolve()
    if not _is_within(root, documents_dir):
        raise ValueError(f"--runtime-root must stay inside {documents_dir}: {root}")
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _runtime_benchmark(runtime_root: Path) -> str | None:
    identity_path = runtime_root / RUNTIME_BENCHMARK_IDENTITY_FILENAME
    if not identity_path.exists():
        if not runtime_root.exists() or not any(runtime_root.iterdir()):
            return None
        # The only runtime format predating this marker is SuperGPQA.
        return "supergpqa"
    try:
        payload = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("Runtime benchmark identity is unreadable.") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Runtime benchmark identity is invalid.")
    benchmark = payload.get("benchmark", "supergpqa")
    if benchmark not in {"supergpqa", "arc-agi", "open-ended"}:
        raise RuntimeError("Runtime benchmark identity is invalid.")
    return str(benchmark)


def _check_runtime_benchmark(runtime_root: Path, requested: str) -> None:
    existing = _runtime_benchmark(runtime_root)
    if existing is not None and existing != requested:
        raise SystemExit(
            f"error: runtime belongs to benchmark {existing}; cannot use {requested}"
        )


def _claim_runtime_benchmark(runtime_root: Path, requested: str) -> None:
    _check_runtime_benchmark(runtime_root, requested)
    identity_path = runtime_root / RUNTIME_BENCHMARK_IDENTITY_FILENAME
    if identity_path.exists():
        return
    _write_json_file_atomic(
        identity_path,
        {
            "format": "metalanguage-runtime-benchmark",
            "version": 1,
            "benchmark": requested,
        },
    )


def _resolve_runtime_path(value: str, runtime_root: Path, label: str) -> Path:
    raw_path = Path(value).expanduser()
    path = raw_path.resolve() if raw_path.is_absolute() else (runtime_root / raw_path).resolve()
    if not _is_within(path, runtime_root):
        raise ValueError(f"{label} must stay inside --runtime-root {runtime_root}: {path}")
    return path


def _configure_runtime_environment(
    runtime_root: Path, *, include_huggingface: bool = True
) -> Path:
    cache_root = runtime_root / "cache"
    dataset_cache_dir = cache_root / "huggingface_datasets"
    env_dirs = {
        "XDG_CACHE_HOME": cache_root / "xdg",
        "TMPDIR": runtime_root / "tmp" / "process",
    }
    if include_huggingface:
        env_dirs.update(
            {
                "HF_HOME": cache_root / "huggingface",
                "HF_DATASETS_CACHE": dataset_cache_dir,
            }
        )
    for name, path in env_dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    return dataset_cache_dir


def _create_benchmark_driver(
    args: argparse.Namespace,
    *,
    arc_benchmark_state_path: Path,
    problem_queue_path: Path,
    task_store_dir: Path,
    dataset_cache_dir: Path,
    existing_records: list[dict[str, Any]],
    open_ended_task: OpenEndedTask | None = None,
    open_ended_state_dir: Path | None = None,
) -> BenchmarkDriver:
    if args.benchmark == "open-ended":
        if open_ended_task is None or open_ended_state_dir is None:
            raise ValueError("open-ended task configuration was not resolved")
        return OpenEndedBenchmarkDriver(
            OpenEndedConfig(
                task=open_ended_task,
                state_dir=open_ended_state_dir,
            )
        )
    if args.benchmark == "arc-agi":
        return ArcAgiBenchmarkDriver(
            ArcAgiConfig(
                state_path=arc_benchmark_state_path,
                seed=args.seed,
                problem_pool_size=args.problem_pool_size,
            )
        )
    return SuperGpqaBenchmarkDriver(
        SuperGpqaConfig(
            dataset_name=args.dataset_name,
            split=args.split,
            config_name=args.config_name,
            seed=args.seed,
            question_key=args.question_key,
            answer_key=args.answer_key,
            id_key=args.id_key,
            difficulty_filter=args.difficulty_filter,
            start_task_index=args.start_task_index,
            problem_pool_size=args.problem_pool_size,
            queue_path=problem_queue_path,
            task_store_dir=task_store_dir,
            dataset_cache_dir=dataset_cache_dir,
            historical_run_records=tuple(existing_records),
            backend=args.worker_backend,
        )
    )


def _validate_benchmark_backend(benchmark: str, worker_backend: str) -> None:
    if benchmark == "arc-agi" and worker_backend not in {"codex", "opencode"}:
        raise SystemExit(
            "error: --benchmark arc-agi currently requires --worker-backend codex or opencode"
        )


def _validate_opencode_containment(
    benchmark: str, sandbox_mode: str, network_mode: str
) -> None:
    if sandbox_mode == "unsafe-none" and benchmark != "open-ended":
        raise RuntimeError(
            "OpenCode benchmark workers require --opencode-sandbox-mode=bubblewrap"
        )
    if network_mode != "allow":
        raise RuntimeError(
            "OpenCode's HTTP server boundary cannot safely use an isolated network namespace; "
            "--opencode-network-mode=none is fail-closed"
        )


def _worker_backend_resume_compatible(
    record: dict[str, Any],
    args: argparse.Namespace,
    *,
    effective_initial_prompt: str | None = None,
    require_effective_prompt: bool = False,
) -> bool:
    if record.get("worker_backend", "openrouter") != args.worker_backend:
        return False
    if args.worker_backend == "codex":
        return record.get("codex_base_instructions_mode", "codex") == (
            args.codex_base_instructions_mode
        )
    if args.worker_backend == "opencode":
        allowed_versions = tuple(
            version.strip()
            for version in getattr(
                args,
                "opencode_allowed_versions",
                ",".join(SOURCE_AUDITED_OPENCODE_VERSIONS),
            ).split(",")
            if version.strip()
        )
        expected_worker_script = resolve_opencode_worker_script(
            Path(args.opencode_worker_script)
            if getattr(args, "opencode_worker_script", None)
            else None
        )
        expected_bun_bin = resolve_bun_bin(
            Path(args.opencode_bun_bin)
            if getattr(args, "opencode_bun_bin", None)
            else None
        )
        recorded_worker_script = record.get("opencode_worker_script")
        if recorded_worker_script is None:
            recorded_worker_script = record.get("opencode_runner_bin")
        expected_fingerprint = {
            "opencode_runtime_version": getattr(args, "_opencode_runtime_version", None),
            "opencode_bin_sha256": getattr(args, "_opencode_bin_sha256", None),
            "opencode_bun_version": getattr(args, "_opencode_bun_version", None),
            "opencode_bun_sha256": getattr(args, "_opencode_bun_sha256", None),
            "opencode_worker_sha256": getattr(args, "_opencode_worker_sha256", None),
            "opencode_python_sha256": getattr(args, "_opencode_python_sha256", None),
            "opencode_auth_sha256": getattr(args, "_opencode_auth_sha256", None),
            "opencode_provider_env_sha256": getattr(
                args, "_opencode_provider_env_sha256", None
            ),
            "opencode_custom_provider_sha256": getattr(
                args, "_opencode_custom_provider_sha256", None
            ),
            "opencode_custom_provider": getattr(
                args, "_opencode_custom_provider", None
            ),
            "opencode_allowed_bun_versions": list(
                getattr(args, "_opencode_allowed_bun_versions", SOURCE_AUDITED_BUN_VERSIONS)
            ),
            "opencode_server_startup_timeout_seconds": getattr(
                args, "opencode_server_startup_timeout_seconds", 15
            ),
            "opencode_worker_timeout_seconds": getattr(
                args, "worker_timeout_seconds", DEFAULT_WORKER_TIMEOUT_SECONDS
            ),
            "opencode_sandbox_mode": getattr(args, "opencode_sandbox_mode", "bubblewrap"),
            "opencode_network_mode": getattr(args, "opencode_network_mode", "allow"),
            "opencode_bubblewrap_bin": getattr(args, "_opencode_bubblewrap_bin", None),
            "opencode_bubblewrap_version": getattr(
                args, "_opencode_bubblewrap_version", None
            ),
            "opencode_bubblewrap_sha256": getattr(
                args, "_opencode_bubblewrap_sha256", None
            ),
            "opencode_system_instructions_sha256": getattr(
                args, "_opencode_system_instructions_sha256", None
            ),
            "opencode_configured_initial_prompt_sha256": getattr(
                args, "_opencode_configured_initial_prompt_sha256", None
            ),
            "opencode_provider_env_names": list(
                getattr(args, "_opencode_provider_env_names", ())
            ),
        }
        effective_prompt_sha256 = record.get(
            "opencode_effective_initial_prompt_sha256"
        )
        prompt_identity_matches = isinstance(effective_prompt_sha256, str) and bool(
            effective_prompt_sha256
        )
        if effective_initial_prompt is not None:
            prompt_identity_matches = effective_prompt_sha256 == text_sha256(
                effective_initial_prompt
            )
        elif record.get("bootstrap_seed_used") is True:
            prompt_identity_matches = effective_prompt_sha256 == getattr(
                args, "_opencode_configured_initial_prompt_sha256", None
            )
        elif require_effective_prompt:
            prompt_identity_matches = False
        return (
            record.get("opencode_base_instructions_mode", "opencode")
            == args.opencode_base_instructions_mode
            and record.get("opencode_agent") == args.opencode_agent
            and record.get("opencode_variant") == args.opencode_variant
            and tuple(
                record.get(
                    "opencode_allowed_versions",
                    SOURCE_AUDITED_OPENCODE_VERSIONS,
                )
            )
            == allowed_versions
            and record.get("opencode_auth_source", "environment")
            == (
                "file"
                if getattr(args, "opencode_auth_file", None)
                else "environment"
            )
            and (
                recorded_worker_script is None
                or Path(recorded_worker_script).resolve() == expected_worker_script
            )
            and (
                record.get("opencode_bun_bin") is None
                or Path(record["opencode_bun_bin"]).resolve() == expected_bun_bin
            )
            and all(record.get(key) == value for key, value in expected_fingerprint.items())
            and prompt_identity_matches
        )
    return True


def _ensure_runtime_bootstrap_seed(bootstrap_seed_dir: Path) -> None:
    if bootstrap_seed_dir.exists():
        return
    if not BUNDLED_BOOTSTRAP_SEED_DIR.exists():
        return
    bootstrap_seed_dir.mkdir(parents=True, exist_ok=True)
    copy_seed_workspace(BUNDLED_BOOTSTRAP_SEED_DIR, bootstrap_seed_dir)


def _snapshot_workspace_files(root: Path) -> dict[Path, tuple[int, int]]:
    """Return file signatures keyed by relative path for all files under root."""
    snapshot: dict[Path, tuple[int, int]] = {}
    if not root.exists():
        return snapshot
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        stat = path.stat()
        snapshot[rel] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _shared_workspace_events(
    *,
    before: dict[Path, tuple[int, int]],
    after: dict[Path, tuple[int, int]],
    task_index: int,
    task_id: str,
    rollout_index: int,
    rollout_username: str,
    command_index: int,
    command: str,
    working_directory: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for rel in sorted(set(before) | set(after)):
        before_sig = before.get(rel)
        after_sig = after.get(rel)
        if before_sig == after_sig:
            continue
        if before_sig is None:
            event = "created"
        elif after_sig is None:
            event = "deleted"
        else:
            event = "modified"
        record: dict[str, Any] = {
            "timestamp": timestamp,
            "task_index": task_index,
            "task_id": task_id,
            "rollout_index": rollout_index,
            "rollout_username": rollout_username,
            "command_index": command_index,
            "event": event,
            "path": str(rel),
            "working_directory": working_directory,
            "command": command[:1000],
        }
        if before_sig is not None:
            record["previous_size"] = before_sig[0]
        if after_sig is not None:
            record["size"] = after_sig[0]
        events.append(record)
    return events


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_shared_attribution(
    *,
    durable_log_path: Path,
    events: list[dict[str, Any]],
) -> None:
    if not events:
        return
    _append_jsonl(durable_log_path, events)


def _cleanup_rollout_shared_writes(root: Path, before: dict[Path, tuple[int, int]]) -> None:
    """Delete files created or modified in the shared workspace by a completed rollout batch."""
    if not root.exists():
        return

    after = _snapshot_workspace_files(root)
    dirty_paths = [rel for rel, sig in after.items() if before.get(rel) != sig]
    for rel in dirty_paths:
        target = root / rel
        if target.exists() and target.is_file():
            target.unlink()

    # Best-effort cleanup of directories emptied by removing rollout files.
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue


def copy_seed_workspace(
    parent_dir: Path,
    workdir: Path,
    *,
    exclude_names: tuple[str, ...] = (),
    consume: bool = False,
) -> None:
    """Copy a workspace directory's contents into a rollout workspace."""
    if not parent_dir.exists():
        return
    excluded = set(exclude_names)
    if consume:
        parent_resolved = parent_dir.resolve()
        workdir_resolved = workdir.resolve()
        if parent_resolved == workdir_resolved or workdir_resolved.is_relative_to(parent_resolved):
            raise ValueError("cannot consume a workspace while copying into itself")

    def _ignore_symlinks(directory: str, names: list[str]) -> list[str]:
        return [name for name in names if (Path(directory) / name).is_symlink()]

    for item in parent_dir.iterdir():
        if item.name in excluded:
            continue
        if item.is_symlink():
            continue
        dest = workdir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True, ignore=_ignore_symlinks)
        elif item.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
    if consume:
        shutil.rmtree(parent_dir)


def consume_spawn_source_workspaces(
    *,
    spawned_child_slots: list[dict[str, Any]],
    rollout_workdir: Path,
) -> list[str]:
    consumed: list[str] = []
    seen: set[Path] = set()
    rollout_root = rollout_workdir.resolve()
    for slot in spawned_child_slots:
        raw_source = slot.get("source_workspace_dir")
        if not isinstance(raw_source, str) or not raw_source:
            continue
        source_dir = Path(raw_source)
        try:
            source_resolved = source_dir.resolve()
        except OSError:
            continue
        if source_resolved in seen:
            continue
        seen.add(source_resolved)
        if (
            source_resolved == rollout_root
            or rollout_root not in source_resolved.parents
            or not source_resolved.is_dir()
        ):
            continue
        shutil.rmtree(source_resolved)
        consumed.append(str(source_resolved))
    return consumed


LIMIT_ERROR_CODES = {
    "context_length_exceeded",
    "max_tokens_exceeded",
    "token_limit_exceeded",
    "string_too_long",
}

LIMIT_ERROR_PATTERNS = (
    "context length",
    "context window",
    "maximum context",
    "max context",
    "token limit",
    "maximum prompt length",
    "prompt is too long",
    "input is too long",
    "string too long",
)


def _text_contains_limit_error(value: Any) -> bool:
    text = json.dumps(value, default=str).lower() if not isinstance(value, str) else value.lower()
    return any(pattern in text for pattern in LIMIT_ERROR_PATTERNS)


def _response_limit_stop(response_json: dict[str, Any]) -> tuple[str | None, str | int | None, str | None]:
    """Return limit stop metadata if OpenRouter encoded a limit as a successful response."""
    errors: list[dict[str, Any]] = []
    error = response_json.get("error")
    if isinstance(error, dict):
        errors.append(error)
    response = response_json.get("response")
    if isinstance(response, dict):
        response_error = response.get("error")
        if isinstance(response_error, dict):
            errors.append(response_error)

    for error in errors:
        code = error.get("code")
        message = str(error.get("message") or "")
        if code in LIMIT_ERROR_CODES or _text_contains_limit_error(error):
            return "limit_exceeded", code, message

    incomplete = response_json.get("incomplete_details")
    if isinstance(incomplete, dict):
        reason = incomplete.get("reason")
        if reason == "max_output_tokens" or _text_contains_limit_error(incomplete):
            return "limit_exceeded", reason, str(incomplete)

    if response_json.get("status") == "incomplete" and _text_contains_limit_error(response_json):
        return "limit_exceeded", response_json.get("status"), str(response_json.get("incomplete_details") or "")

    if response_json.get("status") == "failed" and _text_contains_limit_error(response_json):
        return "limit_exceeded", response_json.get("status"), str(response_json.get("error") or "")

    for item in response_json.get("output", []):
        if not isinstance(item, dict):
            continue
        finish_reason = item.get("finish_reason") or item.get("status")
        if finish_reason == "length":
            return "limit_exceeded", "length", "OpenRouter returned finish/status length."

    return None, None, None


def _api_error_limit_stop(exc: OpenRouterAPIError) -> tuple[str | None, str | int | None, str | None]:
    if exc.error_code in LIMIT_ERROR_CODES or _text_contains_limit_error(exc.response_body):
        return "limit_exceeded", exc.error_code, exc.message
    return None, None, None


def _spawn_child_continuation(
    *,
    context: dict[str, Any],
    args: dict[str, Any],
    progress_callback: Any = None,
) -> dict[str, Any]:
    source_rollout_index = int(context["rollout_index"])
    state = _read_json_file(Path(str(context["spawn_slots_path"])), {})
    slots = state.get("slots") if isinstance(state, dict) else None
    if isinstance(slots, list):
        existing_slot = _slot_for_source_rollout(slots, source_rollout_index)
        if existing_slot is not None:
            raw_prompt = args.get("prompt")
            return _already_spawned_failure(
                source_rollout_index=source_rollout_index,
                slot=existing_slot,
                prompt_chars=len(raw_prompt) if isinstance(raw_prompt, str) else None,
            )

    child_prompt, workspace_dir_arg, error = _parse_spawn_child_arguments(args)
    if error is not None or child_prompt is None:
        return _spawn_failure(
            error or "invalid spawn_child arguments",
            error_code="invalid_spawn_child_arguments",
            retryable=True,
        )
    source_workspace_dir, error = _resolve_spawn_workspace_dir(context, workspace_dir_arg)
    if error is not None:
        return _spawn_failure(
            error or "invalid workspace_dir",
            error_code="invalid_child_workspace",
            retryable=True,
        )

    parent_instance_uuid = str(context["instance_uuid"])
    item_ref = _spawn_item_ref(context)
    source_id = item_ref.source_id or item_ref.item_id
    item_id = item_ref.item_id
    item_index = item_ref.item_index
    child_instance_uuid = new_instance_uuid()

    def _progress(event: str, **fields: Any) -> None:
        payload = {
            "parent_instance_uuid": parent_instance_uuid,
            "child_instance_uuid": child_instance_uuid,
            **fields,
        }
        if progress_callback is not None:
            progress_callback(f"spawn_child_{event}", **payload)
            return
        append_progress_log(
            Path(str(context["progress_log"])),
            threading.Lock(),
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": f"spawn_child_{event}",
                "generation": int(context["generation"]),
                "seed": int(context["seed"]),
                "task_index": int(context["task_index"]),
                "problem_task_index": item_index,
                "rollout_index": int(context["rollout_index"]),
                "rollout_username": str(context["rollout_username"]),
                "task_id": source_id,
                "problem_uid": item_id,
                **payload,
            },
        )

    try:
        slot_result = _record_spawned_child(
            context=context,
            child_instance_uuid=child_instance_uuid,
            child_prompt=child_prompt,
            source_workspace_dir=source_workspace_dir,
        )
        event = "spawned" if slot_result.get("child_spawned") else "failed"
        _progress(event, **slot_result)
        return slot_result
    except BaseException as exc:
        result = _spawn_failure(
            f"{type(exc).__name__}: {exc}",
            error_code="child_workspace_copy_failed",
            retryable=True,
            child_instance_uuid=child_instance_uuid,
            slot_index=int(context["rollout_index"]),
            prompt_chars=len(child_prompt),
        )
        _progress("failed", **result)
        return result


def run_worker(
    *,
    api_key: str,
    model: str,
    workdir: Path,
    seed_output_dir: Path,
    archive_repo_dir: Path,
    shared_workspace_dir: Path,
    worker_state_dir: Path,
    shared_workspace_write_log: Path,
    shared_workspace_lock: threading.Lock,
    task_index: int,
    task_id: str,
    rollout_index: int,
    rollout_username: str,
    timeout_seconds: int,
    bash_timeout_seconds: int,
    openrouter_max_retries: int,
    continuation_context: dict[str, Any],
    benchmark_driver: BenchmarkDriver,
    rollout_benchmark: RolloutBenchmark,
    initial_user_text: str,
    progress_callback: Any = None,
) -> WorkerResult:
    """Run a multi-turn tool-calling worker loop and return final assistant text."""
    conversation: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": initial_user_text,
                }
            ],
        }
    ]

    final_text = ""
    command_index = 0
    turn_count = 0
    spawned_child_slots: list[dict[str, Any]] = []
    started_at = time.monotonic()

    while True:
        turn_count += 1
        elapsed_seconds = time.monotonic() - started_at
        if elapsed_seconds > timeout_seconds:
            if progress_callback is not None:
                progress_callback(
                    "worker_timeout",
                    elapsed_seconds=round(elapsed_seconds, 3),
                    turn_count=turn_count,
                    timeout_seconds=timeout_seconds,
                )
            return WorkerResult(
                final_text=final_text,
                status="timeout",
                stop_reason="worker_timeout",
                error_code="worker_timeout",
                error_message=f"Worker exceeded {timeout_seconds} seconds.",
            )
        if progress_callback is not None:
            progress_callback(
                "worker_turn_started",
                elapsed_seconds=round(elapsed_seconds, 3),
                turn_count=turn_count,
                conversation_items=len(conversation),
            )
        def retry_callback(event: dict[str, Any]) -> None:
            if progress_callback is not None:
                progress_callback(
                    "worker_api_retry",
                    elapsed_seconds=round(time.monotonic() - started_at, 3),
                    turn_count=turn_count,
                    **event,
                )

        try:
            response = call_openrouter_with_tools(
                api_key=api_key,
                model=model,
                input_items=conversation,
                tools=[
                    bash_tool,
                    *rollout_benchmark.model_metadata.get("tools", []),
                    spawn_child_tool,
                ],
                tool_choice="auto",
                timeout=120,
                max_retries=openrouter_max_retries,
                retry_callback=retry_callback if progress_callback is not None else None,
            )
        except OpenRouterAPIError as exc:
            status, code, message = _api_error_limit_stop(exc)
            if status is not None:
                return WorkerResult(
                    final_text=final_text,
                    status=status,
                    stop_reason="api_limit_error",
                    error_code=code,
                    error_message=message,
                )
            raise

        if not isinstance(response, dict):
            raise RuntimeError("Unexpected non-JSON response in non-stream mode.")

        status, code, message = _response_limit_stop(response)
        if status is not None:
            return WorkerResult(
                final_text=_extract_text_from_response(response) or final_text,
                status=status,
                stop_reason="response_limit",
                error_code=code,
                error_message=message,
            )

        tool_calls = get_tool_calls(response)
        if progress_callback is not None:
            progress_callback(
                "worker_turn_completed",
                elapsed_seconds=round(time.monotonic() - started_at, 3),
                turn_count=turn_count,
                tool_call_count=len(tool_calls),
                response_status=response.get("status"),
            )
        if not tool_calls:
            final_text = _extract_text_from_response(response)
            break

        for call in tool_calls:
            call_id = call.get("call_id")
            if not isinstance(call_id, str) or not call_id:
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Your previous tool call was malformed (missing call_id). "
                                    "Please retry with a valid function call."
                                ),
                            }
                        ],
                    }
                )
                continue

            args: dict[str, Any]
            raw_args = call.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            tool_name = str(call.get("name") or "")
            command = str(args.get("command", "")).strip()
            benchmark_tool_result = benchmark_driver.handle_tool(
                rollout_benchmark,
                tool_name,
                args,
            )
            if benchmark_tool_result is not None:
                tool_result = benchmark_tool_result
            elif tool_name == "spawn_child":
                tool_result = _spawn_child_continuation(
                    context=continuation_context,
                    args=args,
                    progress_callback=progress_callback,
                )
                if tool_result.get("child_spawned"):
                    spawned_child_slots.append(tool_result)
            elif tool_name != "run_bash":
                tool_result = {"error": f"unsupported tool '{call.get('name')}'"}
            elif not command:
                tool_result = {"error": "missing or malformed 'command' argument"}
            else:
                command_index += 1
                if progress_callback is not None:
                    progress_callback(
                        "worker_tool_started",
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                        turn_count=turn_count,
                        command_index=command_index,
                        command=command[:1000],
                    )
                wd = str(args.get("working_directory") or workdir)
                try:
                    resolved_wd = Path(wd).resolve()
                    allowed_roots = [
                        workdir.resolve(),
                        seed_output_dir.resolve(),
                        archive_repo_dir.resolve(),
                        shared_workspace_dir.resolve(),
                    ]
                    safe_wd = str(workdir)
                    for root in allowed_roots:
                        if _is_within(resolved_wd, root):
                            safe_wd = str(resolved_wd)
                            break
                except Exception:
                    safe_wd = str(workdir)
                # A bash command can touch the shared workspace through absolute paths,
                # so serialize command execution while diffing for reliable attribution.
                with shared_workspace_lock:
                    before_shared = _snapshot_workspace_files(shared_workspace_dir)
                    tool_result = _run_bash_tool(
                        command=command,
                        working_directory=safe_wd,
                        worker_state_dir=worker_state_dir,
                        timeout_seconds=bash_timeout_seconds,
                        rollout_username=rollout_username,
                    )
                    after_shared = _snapshot_workspace_files(shared_workspace_dir)
                    shared_events = _shared_workspace_events(
                        before=before_shared,
                        after=after_shared,
                        task_index=task_index,
                        task_id=task_id,
                        rollout_index=rollout_index,
                        rollout_username=rollout_username,
                        command_index=command_index,
                        command=command,
                        working_directory=safe_wd,
                    )
                    _append_shared_attribution(
                        durable_log_path=shared_workspace_write_log,
                        events=shared_events,
                    )
                    if shared_events:
                        tool_result["shared_workspace_writes"] = [
                            {
                                "event": event["event"],
                                "path": event["path"],
                                "rollout_username": rollout_username,
                            }
                            for event in shared_events
                        ]
                if progress_callback is not None:
                    progress_callback(
                        "worker_tool_completed",
                        elapsed_seconds=round(time.monotonic() - started_at, 3),
                        turn_count=turn_count,
                        command_index=command_index,
                        exit_code=tool_result.get("exit_code"),
                        timed_out=tool_result.get("timed_out"),
                    )

            conversation.append(call)
            conversation.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(tool_result),
                }
            )
    return WorkerResult(
        final_text=final_text,
        status="completed",
        stop_reason="final_message",
        metadata={"spawned_child_slots": spawned_child_slots},
    )


def run_codex_worker(
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
    rollout_username: str,
    timeout_seconds: int,
    sandbox_mode: str,
    initial_user_text: str,
    base_instructions: str | None = None,
    continuation_context_path: Path | None = None,
    benchmark_mcp_servers: dict[str, Any] | None = None,
    sensitive_mcp_tools: tuple[tuple[str, str], ...] = (),
    progress_callback: Any = None,
) -> WorkerResult:
    """Run one rollout through the Metalanguage-owned Codex runner."""

    result = run_codex_rollout(
        runner_bin=runner_bin,
        model=model,
        workdir=workdir,
        control_dir=control_dir,
        worker_state_dir=worker_state_dir,
        codex_home=codex_home,
        seed_output_dir=seed_output_dir,
        archive_repo_dir=archive_repo_dir,
        archive_git_dir=archive_git_dir,
        shared_workspace_dir=shared_workspace_dir,
        rollout_username=rollout_username,
        timeout_seconds=timeout_seconds,
        sandbox_mode=sandbox_mode,
        initial_user_text=initial_user_text,
        base_instructions=base_instructions,
        spawn_child_handler_context_path=continuation_context_path,
        benchmark_mcp_servers=benchmark_mcp_servers,
        sensitive_mcp_tools=sensitive_mcp_tools,
        progress_callback=progress_callback,
    )
    metadata = {
        key: result.get(key)
        for key in [
            "thread_id",
            "session_id",
            "request_path",
            "stderr_path",
            "events_path",
        ]
        if result.get(key) is not None
    }
    return WorkerResult(
        final_text=str(result.get("final_text") or ""),
        status=str(result.get("status") or "error"),
        stop_reason=result.get("stop_reason"),
        error_code=result.get("error_code"),
        error_message=result.get("error_message"),
        metadata=metadata,
    )


def run_opencode_worker(
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
    allowed_bun_versions: tuple[str, ...] = SOURCE_AUDITED_BUN_VERSIONS,
    startup_timeout_seconds: int = 15,
    provider_env_names: tuple[str, ...] = (),
    provider_environment: dict[str, str] | None = None,
    custom_provider: dict[str, Any] | None = None,
    sandbox_mode: str = "bubblewrap",
    sandbox_network: str = "allow",
    bubblewrap_bin: Path | None = None,
    sandbox_read_only_roots: tuple[Path, ...] = (),
    sandbox_read_only_mounts: tuple[tuple[Path, Path], ...] = (),
    sandbox_writable_roots: tuple[Path, ...] = (),
    sandbox_masked_paths: tuple[Path, ...] = (),
    progress_callback: Any = None,
) -> WorkerResult:
    """Run one rollout through the Metalanguage-owned TypeScript/Bun worker."""

    result = run_opencode_rollout(
        worker_script=worker_script,
        bun_bin=bun_bin,
        opencode_bin=opencode_bin,
        model=model,
        workdir=workdir,
        control_dir=control_dir,
        worker_state_dir=worker_state_dir,
        timeout_seconds=timeout_seconds,
        initial_user_text=initial_user_text,
        system_instructions=system_instructions,
        continuation_context_path=continuation_context_path,
        benchmark_mcp_servers=benchmark_mcp_servers,
        sensitive_mcp_tools=sensitive_mcp_tools,
        auth_file=auth_file,
        agent=agent,
        variant=variant,
        allowed_versions=allowed_versions,
        allowed_bun_versions=allowed_bun_versions,
        startup_timeout_seconds=startup_timeout_seconds,
        provider_env_names=provider_env_names,
        provider_environment=provider_environment,
        custom_provider=custom_provider,
        sandbox_mode=sandbox_mode,
        sandbox_network=sandbox_network,
        bubblewrap_bin=bubblewrap_bin,
        sandbox_read_only_roots=sandbox_read_only_roots,
        sandbox_read_only_mounts=sandbox_read_only_mounts,
        sandbox_writable_roots=sandbox_writable_roots,
        sandbox_masked_paths=sandbox_masked_paths,
        progress_callback=progress_callback,
    )
    metadata = {
        key: result.get(key)
        for key in [
            "thread_id",
            "session_id",
            "runtime_version",
            "request_path",
            "stderr_path",
            "events_path",
            "isolated_state_cleaned",
            "mcp_process_pids",
        ]
        if result.get(key) is not None
    }
    return WorkerResult(
        final_text=str(result.get("final_text") or ""),
        status=str(result.get("status") or "error"),
        stop_reason=result.get("stop_reason"),
        error_code=result.get("error_code"),
        error_message=result.get("error_message"),
        metadata=metadata,
    )


def resolve_codex_base_instructions(mode: str) -> str | None:
    """Return fixed Codex base instructions, or None for Codex defaults."""
    if mode == "codex":
        return None
    if mode == "read-readme":
        return CODEX_READ_README_BASE_INSTRUCTIONS
    raise ValueError(f"Unknown Codex base instructions mode: {mode}")


def resolve_opencode_system_instructions(mode: str) -> str | None:
    """Return an exact per-request OpenCode system instruction override."""
    if mode == "opencode":
        return None
    if mode == "read-readme":
        return READ_README_TASK_INSTRUCTIONS
    raise ValueError(f"Unknown OpenCode system instructions mode: {mode}")


def persist_episode_outputs(temp_dir: Path, dest_root: Path, task_id: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_root / f"{ts}_{task_id}"
    shutil.copytree(temp_dir, dest, dirs_exist_ok=True, symlinks=True)
    return dest


def append_run_log(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_progress_log(log_path: Path, lock: threading.Lock, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_existing_run_records(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []

    records: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            raw = line.strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def load_parent_pool(parent_pool_path: Path) -> list[dict[str, Any]]:
    if not parent_pool_path.exists():
        return []
    try:
        raw = json.loads(parent_pool_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []

    slots: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        slot = dict(item)
        prompt = _slot_prompt(slot)
        if prompt is None:
            continue
        if "prompt" not in slot:
            slot["prompt"] = prompt
        slots.append(slot)
    return slots


def save_parent_pool(parent_pool_path: Path, parent_pool: list[dict[str, Any]]) -> None:
    parent_pool_path.parent.mkdir(parents=True, exist_ok=True)
    parent_pool_path.write_text(
        json.dumps(parent_pool, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def create_archive_worktree(
    *,
    archive_repo_dir: Path,
    worktree_root: Path,
    branch: str,
    git_lock: threading.Lock,
) -> ArchiveWorktree:
    """Create an isolated archive worktree for one parallel rollout."""
    worktree_root.mkdir(parents=True, exist_ok=True)
    worktree_path = (worktree_root / _sanitize_for_path(branch)).resolve()
    shutil.rmtree(worktree_path, ignore_errors=True)

    with git_lock:
        base_commit = _run_git(["rev-parse", "HEAD"], archive_repo_dir).stdout.strip()
        _run_git(["worktree", "prune"], archive_repo_dir, check=False)
        _run_git(["branch", "-D", branch], archive_repo_dir, check=False)
        _run_git(["worktree", "add", "-B", branch, str(worktree_path), "HEAD"], archive_repo_dir)

    return ArchiveWorktree(path=worktree_path, branch=branch, base_commit=base_commit)


def finalize_archive_worktree(
    *,
    archive_repo_dir: Path,
    worktree: ArchiveWorktree,
    git_lock: threading.Lock,
) -> dict[str, Any]:
    """Keep committed archive changes, discard uncommitted edits, and remove the worktree."""
    result: dict[str, Any] = {
        "archive_worktree_dir": str(worktree.path),
        "archive_branch": worktree.branch,
        "archive_base_commit": worktree.base_commit,
        "archive_head_commit": worktree.base_commit,
        "archive_committed": False,
        "archive_merged": False,
    }

    try:
        if worktree.path.exists():
            _run_git(["reset", "--hard", "HEAD"], worktree.path, check=False)
            _run_git(["clean", "-fd"], worktree.path, check=False)
            head_commit = _run_git(["rev-parse", "HEAD"], worktree.path).stdout.strip()
            result["archive_head_commit"] = head_commit
            result["archive_committed"] = head_commit != worktree.base_commit

            with git_lock:
                merge_failed = False
                if result["archive_committed"]:
                    merge = _run_git(["merge", "--no-ff", "--no-edit", worktree.branch], archive_repo_dir, check=False)
                    if merge.returncode != 0:
                        _run_git(["merge", "--abort"], archive_repo_dir, check=False)
                        result["archive_merge_error"] = (merge.stderr or merge.stdout).strip()
                        merge_failed = True
                    else:
                        result["archive_merged"] = True

                _run_git(["worktree", "remove", "--force", str(worktree.path)], archive_repo_dir, check=False)
                if not merge_failed:
                    delete_args = ["branch", "-d" if result["archive_merged"] else "-D", worktree.branch]
                    _run_git(delete_args, archive_repo_dir, check=False)
    finally:
        shutil.rmtree(worktree.path, ignore_errors=True)

    return result


def discard_archive_worktree(
    *,
    archive_repo_dir: Path,
    worktree_root: Path,
    branch: str,
    git_lock: threading.Lock,
) -> None:
    """Remove an unfinalized rollout worktree and branch after setup failure."""

    worktree_path = (worktree_root / _sanitize_for_path(branch)).resolve()
    try:
        with git_lock:
            _run_git(
                ["worktree", "remove", "--force", str(worktree_path)],
                archive_repo_dir,
                check=False,
            )
            _run_git(["worktree", "prune"], archive_repo_dir, check=False)
            _run_git(["branch", "-D", branch], archive_repo_dir, check=False)
    finally:
        shutil.rmtree(worktree_path, ignore_errors=True)
        try:
            worktree_root.rmdir()
        except OSError:
            pass


def ensure_local_world_repo(repo_path: Path) -> None:
    """Ensure a local persistent git repo exists with an initial commit."""
    repo_path.mkdir(parents=True, exist_ok=True)
    git_dir = repo_path / ".git"

    if not git_dir.exists():
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "config", "user.name", "metalanguage-bot"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "bot@local"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )

    has_commits = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).returncode == 0

    if not has_commits:
        genesis_file = repo_path / "WORLD.md"
        genesis_file.write_text(
            (
                "# Local world repo\n\n"
                "Persistent local git substrate for rollout lineage.\n\n"
                "Archive edits persist only when they are committed to git. Each rollout "
                "gets a temporary archive worktree; at finalization, committed changes are "
                "merged back and uncommitted edits are discarded.\n"
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", "WORLD.md"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "world: genesis"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )


def _positive_int_argument(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one RLVR episode.")
    parser.add_argument(
        "--benchmark",
        choices=["supergpqa", "arc-agi", "open-ended"],
        default="supergpqa",
        help="Benchmark runtime to use.",
    )
    parser.add_argument(
        "--task-file",
        default=None,
        help=(
            "UTF-8 Markdown task for --benchmark open-ended. Required when "
            "initializing that runtime; later steps can use its persisted copy."
        ),
    )
    parser.add_argument("--dataset-name", default="m-a-p/SuperGPQA")
    parser.add_argument("--split", default="train")
    parser.add_argument("--config-name", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--worker-backend",
        choices=["openrouter", "codex", "opencode"],
        default="openrouter",
        help="Worker runtime to use for rollouts.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument(
        "--num-rollouts",
        type=int,
        default=DEFAULT_NUM_ROLLOUTS,
        help="Configured rollout population size for every batch.",
    )
    parser.add_argument(
        "--worker-timeout-seconds",
        type=int,
        default=DEFAULT_WORKER_TIMEOUT_SECONDS,
        help="Maximum wall-clock seconds per rollout before marking that rollout failed.",
    )
    parser.add_argument(
        "--bash-timeout-seconds",
        type=int,
        default=DEFAULT_BASH_TIMEOUT_SECONDS,
        help="Maximum wall-clock seconds per worker bash command before returning a command timeout.",
    )
    parser.add_argument(
        "--openrouter-max-retries",
        type=int,
        default=DEFAULT_OPENROUTER_MAX_RETRIES,
        help="Maximum retries for transient OpenRouter request failures per model turn.",
    )
    parser.add_argument(
        "--fail-on-rollout-error",
        action="store_true",
        help=(
            "Exit nonzero when any rollout has a worker/runtime error, even if "
            "next-iteration children were spawned."
        ),
    )
    parser.add_argument("--question-key", default=None)
    parser.add_argument("--answer-key", default=None)
    parser.add_argument("--id-key", default=None)
    parser.add_argument(
        "--difficulty-filter",
        default="hard",
        help=(
            "Comma-separated dataset difficulty values to include in the problem pool. "
            "Use 'all' to disable filtering. Defaults to hard."
        ),
    )
    parser.add_argument(
        "--all-tasks",
        action="store_true",
        help="Process all tasks in the split instead of one sampled task.",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=None,
        help="Optional number of tasks to process when --all-tasks is set.",
    )
    parser.add_argument(
        "--start-task-index",
        type=int,
        default=0,
        help="Start index in the shuffled dataset stream when --all-tasks or --step is set.",
    )
    parser.add_argument(
        "--step",
        action="store_true",
        help="Process exactly the next incomplete task iteration from resume state, then exit.",
    )
    parser.add_argument(
        "--runtime-root",
        default=str(DEFAULT_RUNTIME_ROOT),
        help="Root for all generated run state. Must stay inside ~/Documents.",
    )
    parser.add_argument("--runs-log", default="logs/runs.jsonl")
    parser.add_argument(
        "--progress-log",
        default="logs/progress.jsonl",
        help="JSONL progress events for rollout starts, worker turns, tools, scoring, and persistence.",
    )
    parser.add_argument("--outputs-dir", default="logs/episodes")
    parser.add_argument(
        "--fixed-temp-dir",
        default="logs/tmp/current_episode",
        help="Fixed working directory reused across tasks.",
    )
    parser.add_argument(
        "--rollout-temp-root",
        default="logs/tmp/rollout_chain",
        help="Root path for per-task carryover directories.",
    )
    parser.add_argument(
        "--bootstrap-seed-dir",
        default="seeds/bootstrap",
        help=(
            "Bootstrap seed directory used before any parent slot exists. "
            "Resolved under --runtime-root unless absolute."
        ),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume logic and always start a fresh run.",
    )
    parser.add_argument(
        "--task-store-dir",
        default="logs/task_store",
        help=(
            "Private task store path (outside rollout workspaces) for full dataset rows "
            "including ground truth."
        ),
    )
    parser.add_argument(
        "--problem-queue",
        default="logs/problem_queue.json",
        help=(
            "Persistent problem-pool state for solved IDs and cursor. Resolved under "
            "--runtime-root unless absolute."
        ),
    )
    parser.add_argument(
        "--problem-pool-size",
        type=_positive_int_argument,
        default=None,
        help=(
            "Maximum number of benchmark records exposed per iteration. SuperGPQA "
            "samples currently unsolved problems; ARC samples its reusable public "
            "environment catalog. Defaults to uncapped."
        ),
    )
    parser.add_argument(
        "--archive-repo-dir",
        default="archive/world_repo",
        help="Durable cross-lineage Git archive exposed to every rollout.",
    )
    parser.add_argument(
        "--codex-home",
        default=str(DEFAULT_CODEX_HOME),
        help="Codex home used for auth/config when --worker-backend=codex.",
    )
    parser.add_argument(
        "--codex-runner-bin",
        default=None,
        help=(
            "Optional prebuilt metalanguage-codex-runner binary. If omitted, "
            "the default crate target path is used and must already exist."
        ),
    )
    parser.add_argument(
        "--codex-build-runner",
        action="store_true",
        help="Build the Codex runner before starting. Off by default.",
    )
    parser.add_argument(
        "--codex-runner-release",
        action="store_true",
        help="Use the release-profile Codex runner path, and build release when --codex-build-runner is set.",
    )
    parser.add_argument(
        "--codex-sandbox-mode",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="workspace-write",
        help="Codex sandbox mode for rollout workers.",
    )
    parser.add_argument(
        "--codex-initial-prompt",
        default=READ_README_TASK_INSTRUCTIONS,
        help="Initial user text submitted to the Codex runner for each rollout.",
    )
    parser.add_argument(
        "--codex-base-instructions-mode",
        choices=["codex", "read-readme"],
        default="read-readme",
        help=(
            "Codex base-instructions mode. 'codex' uses the model catalog default; "
            "'read-readme' uses the fixed scaffold task instruction."
        ),
    )
    parser.add_argument(
        "--opencode-bin",
        default=None,
        help="OpenCode executable. Defaults to the opencode resolved from PATH.",
    )
    parser.add_argument(
        "--opencode-worker-script",
        "--opencode-runner-bin",
        dest="opencode_worker_script",
        default=None,
        help=(
            "Optional TypeScript/Bun OpenCode worker script. The legacy "
            "--opencode-runner-bin spelling is retained as an alias."
        ),
    )
    parser.add_argument(
        "--opencode-bun-bin",
        default=None,
        help="Bun executable for the native TypeScript OpenCode worker.",
    )
    parser.add_argument(
        "--opencode-build-runner",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--opencode-runner-release",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--opencode-auth-file",
        default=None,
        help=(
            "Optional read-only OpenCode auth JSON copied into each isolated rollout "
            "through OPENCODE_AUTH_CONTENT. Provider environment credentials work without it."
        ),
    )
    parser.add_argument(
        "--opencode-agent",
        default=None,
        help="Optional OpenCode primary agent name.",
    )
    parser.add_argument(
        "--opencode-variant",
        default=None,
        help="Optional OpenCode model variant.",
    )
    parser.add_argument(
        "--opencode-allowed-versions",
        default=",".join(SOURCE_AUDITED_OPENCODE_VERSIONS),
        help="Comma-separated exact OpenCode CLI versions accepted by the pinned protocol adapter.",
    )
    parser.add_argument(
        "--opencode-server-startup-timeout-seconds",
        type=_positive_int_argument,
        default=15,
        help="Maximum seconds for the private per-rollout OpenCode server to start.",
    )
    parser.add_argument(
        "--opencode-allowed-bun-versions",
        default=",".join(SOURCE_AUDITED_BUN_VERSIONS),
        help="Comma-separated exact Bun versions accepted by the native OpenCode worker.",
    )
    parser.add_argument(
        "--opencode-provider-env",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Additional provider credential variable to pass to OpenCode. May be repeated; "
            "unrelated host environment variables are not inherited."
        ),
    )
    parser.add_argument(
        "--opencode-custom-provider-id",
        default=None,
        help="Safe ID for a custom OpenAI-compatible provider; must match the provider in --model.",
    )
    parser.add_argument(
        "--opencode-custom-provider-name",
        default=None,
        help="Display name for the custom OpenCode provider.",
    )
    parser.add_argument(
        "--opencode-custom-provider-npm",
        choices=["@ai-sdk/openai-compatible", "@ai-sdk/openai"],
        default=None,
        help=(
            "Audited bundled AI SDK package: openai-compatible uses chat completions; "
            "openai uses the Responses API."
        ),
    )
    parser.add_argument(
        "--opencode-custom-provider-base-url",
        default=None,
        help="Custom provider API base URL; non-loopback endpoints require HTTPS.",
    )
    parser.add_argument(
        "--opencode-custom-provider-api-key-env",
        default=None,
        metavar="ENV_VAR",
        help="Environment variable containing the custom provider API key; raw keys are not accepted.",
    )
    parser.add_argument(
        "--opencode-custom-provider-header-env",
        action="append",
        default=[],
        metavar="HEADER=ENV_VAR",
        help="Custom request header sourced from an environment variable. May be repeated.",
    )
    parser.add_argument(
        "--opencode-custom-provider-context-limit",
        type=_positive_int_argument,
        default=None,
        help="Optional custom model context-token limit; requires the output limit.",
    )
    parser.add_argument(
        "--opencode-custom-provider-output-limit",
        type=_positive_int_argument,
        default=None,
        help="Optional custom model output-token limit; requires the context limit.",
    )
    parser.add_argument(
        "--opencode-sandbox-mode",
        choices=["bubblewrap", "unsafe-none"],
        default="bubblewrap",
        help="OpenCode containment mode. Benchmarks require bubblewrap; unsafe-none is open-ended only.",
    )
    parser.add_argument(
        "--opencode-network-mode",
        choices=["allow", "none"],
        default="allow",
        help=(
            "OpenCode sandbox network policy. The server boundary currently supports only explicit "
            "'allow'; 'none' fails closed."
        ),
    )
    parser.add_argument(
        "--opencode-bubblewrap-bin",
        default="/usr/bin/bwrap",
        help="bubblewrap executable used for the OpenCode-only external sandbox.",
    )
    parser.add_argument(
        "--opencode-initial-prompt",
        default=READ_README_TASK_INSTRUCTIONS,
        help="Initial user text submitted to OpenCode for a non-inherited rollout.",
    )
    parser.add_argument(
        "--opencode-base-instructions-mode",
        choices=["opencode", "read-readme"],
        default="read-readme",
        help=(
            "OpenCode system-instruction mode. 'opencode' keeps its defaults; "
            "'read-readme' injects the fixed scaffold instruction through the prompt system field."
        ),
    )
    return parser.parse_args()


def _run_main(active_drivers: list[BenchmarkDriver]) -> None:
    args = parse_args()
    args.difficulty_filter = _normalize_difficulty_filter(args.difficulty_filter)
    difficulty_filter_payload = list(args.difficulty_filter) if args.difficulty_filter is not None else None
    if args.num_rollouts <= 0:
        raise ValueError("--num-rollouts must be > 0")
    if args.worker_timeout_seconds <= 0:
        raise ValueError("--worker-timeout-seconds must be > 0")
    if args.bash_timeout_seconds <= 0:
        raise ValueError("--bash-timeout-seconds must be > 0")
    if args.openrouter_max_retries < 0:
        raise ValueError("--openrouter-max-retries must be >= 0")
    if args.benchmark == "open-ended" and args.problem_pool_size is not None:
        raise SystemExit(
            "error: --problem-pool-size is not valid with --benchmark open-ended"
        )

    unresolved_runtime_root = _resolve_runtime_root(args.runtime_root, create=False)
    _check_runtime_benchmark(unresolved_runtime_root, args.benchmark)
    _validate_benchmark_backend(args.benchmark, args.worker_backend)
    open_ended_state_dir = unresolved_runtime_root / "logs" / "open_ended_task"
    open_ended_task: OpenEndedTask | None = None
    if args.benchmark == "open-ended":
        try:
            open_ended_task = resolve_open_ended_task(
                open_ended_state_dir,
                args.task_file,
            )
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from None
    elif args.task_file is not None:
        raise SystemExit("error: --task-file is only valid with --benchmark open-ended")

    load_dotenv()
    opencode_custom_provider = custom_provider_configuration(
        model=args.model,
        provider_id=args.opencode_custom_provider_id,
        name=args.opencode_custom_provider_name,
        npm=args.opencode_custom_provider_npm,
        base_url=args.opencode_custom_provider_base_url,
        api_key_env=args.opencode_custom_provider_api_key_env,
        header_env=tuple(args.opencode_custom_provider_header_env),
        context_limit=args.opencode_custom_provider_context_limit,
        output_limit=args.opencode_custom_provider_output_limit,
    )
    if opencode_custom_provider is not None and args.worker_backend != "opencode":
        raise ValueError("custom OpenCode provider flags require --worker-backend=opencode")
    opencode_custom_provider_sha256 = custom_provider_fingerprint(
        opencode_custom_provider
    )
    api_key: str | None = os.environ.get("OPENROUTER_API_KEY")
    if args.worker_backend == "openrouter" and not api_key:
        raise RuntimeError(f"OPENROUTER_API_KEY is required. Set it in the environment or {DEFAULT_ENV_PATH}.")
    codex_home = Path(args.codex_home).expanduser().resolve()
    codex_runner_bin: Path | None = None
    if args.worker_backend == "codex":
        codex_runner_bin = resolve_codex_runner_bin(
            Path(args.codex_runner_bin) if args.codex_runner_bin else None,
            release=args.codex_runner_release,
            build=args.codex_build_runner,
        )
    opencode_worker_script: Path | None = None
    opencode_bun_bin: Path | None = None
    opencode_bin: Path | None = None
    opencode_auth_file: Path | None = None
    opencode_allowed_versions = tuple(
        version.strip()
        for version in args.opencode_allowed_versions.split(",")
        if version.strip()
    )
    opencode_allowed_bun_versions = tuple(
        version.strip()
        for version in args.opencode_allowed_bun_versions.split(",")
        if version.strip()
    )
    opencode_bubblewrap_bin: Path | None = None
    opencode_runtime_version: str | None = None
    opencode_bun_version: str | None = None
    opencode_bin_sha256: str | None = None
    opencode_bun_sha256: str | None = None
    opencode_worker_sha256: str | None = None
    opencode_auth_sha256: str | None = None
    opencode_provider_env_names: tuple[str, ...] = ()
    opencode_provider_env_sha256: str | None = None
    opencode_provider_environment: dict[str, str] | None = None
    opencode_credential_mounts: tuple[tuple[Path, Path], ...] = ()
    opencode_python_sha256: str | None = None
    opencode_bubblewrap_version: str | None = None
    opencode_bubblewrap_sha256: str | None = None
    opencode_system_instructions: str | None = None
    opencode_system_instructions_sha256: str | None = None
    opencode_configured_initial_prompt_sha256: str | None = None
    if args.worker_backend == "opencode":
        if not opencode_allowed_versions:
            raise ValueError("--opencode-allowed-versions must contain at least one version")
        if not opencode_allowed_bun_versions:
            raise ValueError("--opencode-allowed-bun-versions must contain at least one version")
        opencode_worker_script = resolve_opencode_worker_script(
            Path(args.opencode_worker_script) if args.opencode_worker_script else None,
        )
        opencode_bun_bin = resolve_bun_bin(
            Path(args.opencode_bun_bin) if args.opencode_bun_bin else None
        )
        opencode_bin = resolve_opencode_bin(
            Path(args.opencode_bin) if args.opencode_bin else None
        )
        if args.opencode_auth_file:
            opencode_auth_file = Path(args.opencode_auth_file).expanduser().resolve()
            if not opencode_auth_file.is_file():
                raise FileNotFoundError(
                    f"OpenCode auth file does not exist: {opencode_auth_file}"
                )
        _validate_opencode_containment(
            args.benchmark, args.opencode_sandbox_mode, args.opencode_network_mode
        )
        if args.opencode_sandbox_mode == "bubblewrap":
            opencode_bubblewrap_bin = resolve_bubblewrap_bin(
                Path(args.opencode_bubblewrap_bin)
            )
            validate_opencode_host_primitives(opencode_bubblewrap_bin)
            opencode_bubblewrap_version = executable_version(opencode_bubblewrap_bin)
            opencode_bubblewrap_sha256 = file_sha256(opencode_bubblewrap_bin)
        opencode_runtime_version = executable_version(opencode_bin)
        opencode_bun_version = executable_version(opencode_bun_bin)
        if opencode_runtime_version not in opencode_allowed_versions:
            raise RuntimeError(
                f"OpenCode version {opencode_runtime_version} is not source-audited"
            )
        if opencode_bun_version not in opencode_allowed_bun_versions:
            raise RuntimeError(f"Bun version {opencode_bun_version} is not source-audited")
        opencode_bin_sha256 = file_sha256(opencode_bin)
        opencode_bun_sha256 = file_sha256(opencode_bun_bin)
        opencode_worker_sha256 = opencode_worker_fingerprint(opencode_worker_script)
        opencode_auth_sha256 = (
            file_sha256(opencode_auth_file) if opencode_auth_file is not None else None
        )
        opencode_provider_env_names = provider_environment_names(
            args.model,
            (
                *tuple(args.opencode_provider_env),
                *custom_provider_environment_names(opencode_custom_provider),
            ),
        )
        opencode_provider_environment, opencode_credential_mounts = (
            prepare_provider_environment(
                opencode_provider_env_names,
                sandbox_mode=args.opencode_sandbox_mode,
            )
        )
        missing_custom_provider_env = [
            name
            for name in custom_provider_environment_names(opencode_custom_provider)
            if name not in opencode_provider_environment
        ]
        if missing_custom_provider_env:
            raise ValueError(
                "custom OpenCode provider environment variables are unset: "
                + ", ".join(missing_custom_provider_env)
            )
        opencode_provider_env_sha256 = provider_environment_fingerprint(
            opencode_provider_env_names,
            sandbox_mode=args.opencode_sandbox_mode,
        )
        opencode_python_sha256 = opencode_python_fingerprint(Path(__file__))
        opencode_system_instructions = resolve_opencode_system_instructions(
            args.opencode_base_instructions_mode
        )
        opencode_system_instructions_sha256 = text_sha256(
            opencode_system_instructions
        )
        opencode_configured_initial_prompt_sha256 = text_sha256(
            args.opencode_initial_prompt
        )
        args._opencode_runtime_version = opencode_runtime_version
        args._opencode_bin_sha256 = opencode_bin_sha256
        args._opencode_bun_version = opencode_bun_version
        args._opencode_bun_sha256 = opencode_bun_sha256
        args._opencode_worker_sha256 = opencode_worker_sha256
        args._opencode_python_sha256 = opencode_python_sha256
        args._opencode_auth_sha256 = opencode_auth_sha256
        args._opencode_provider_env_names = opencode_provider_env_names
        args._opencode_provider_env_sha256 = opencode_provider_env_sha256
        args._opencode_custom_provider_sha256 = opencode_custom_provider_sha256
        args._opencode_custom_provider = opencode_custom_provider
        args._opencode_allowed_bun_versions = opencode_allowed_bun_versions
        args._opencode_bubblewrap_bin = (
            str(opencode_bubblewrap_bin) if opencode_bubblewrap_bin is not None else None
        )
        args._opencode_bubblewrap_version = opencode_bubblewrap_version
        args._opencode_bubblewrap_sha256 = opencode_bubblewrap_sha256
        args._opencode_system_instructions_sha256 = (
            opencode_system_instructions_sha256
        )
        args._opencode_configured_initial_prompt_sha256 = (
            opencode_configured_initial_prompt_sha256
        )

    runtime_root = _resolve_runtime_root(args.runtime_root)
    _claim_runtime_benchmark(runtime_root, args.benchmark)
    runs_log_path = _resolve_runtime_path(args.runs_log, runtime_root, "--runs-log")
    progress_log_path = _resolve_runtime_path(args.progress_log, runtime_root, "--progress-log")
    outputs_dir = _resolve_runtime_path(args.outputs_dir, runtime_root, "--outputs-dir")
    fixed_temp_dir = _resolve_runtime_path(args.fixed_temp_dir, runtime_root, "--fixed-temp-dir")
    rollout_root = _resolve_runtime_path(args.rollout_temp_root, runtime_root, "--rollout-temp-root")
    task_store_dir = _resolve_runtime_path(args.task_store_dir, runtime_root, "--task-store-dir")
    problem_queue_path = _resolve_runtime_path(args.problem_queue, runtime_root, "--problem-queue")
    arc_benchmark_state_path = runtime_root / "logs" / "arc_agi" / "benchmark_state.json"
    archive_repo_dir = _resolve_runtime_path(args.archive_repo_dir, runtime_root, "--archive-repo-dir")
    bootstrap_seed_dir = _resolve_runtime_path(args.bootstrap_seed_dir, runtime_root, "--bootstrap-seed-dir")
    benchmark_events_path = (
        runtime_root / "logs" / "benchmark_events.jsonl"
        if args.benchmark != "open-ended"
        else None
    )
    if benchmark_events_path is not None:
        benchmark_events_path.parent.mkdir(parents=True, exist_ok=True)
        benchmark_events_path.touch(mode=0o600, exist_ok=True)
        os.chmod(benchmark_events_path, 0o600)
    dataset_cache_dir = _configure_runtime_environment(
        runtime_root,
        include_huggingface=args.benchmark == "supergpqa",
    )
    _ensure_runtime_bootstrap_seed(bootstrap_seed_dir)

    ensure_local_world_repo(archive_repo_dir)
    archive_git_lock = threading.Lock()

    rollout_root.mkdir(parents=True, exist_ok=True)
    archive_worktree_root = rollout_root / "archive_worktrees"

    parent_pool_path = rollout_root / "latest_parent_pool.json"
    shared_workspace_dir = rollout_root / "shared_workspace"
    shared_workspace_dir.mkdir(parents=True, exist_ok=True)
    shared_workspace_write_log = rollout_root / "shared_workspace_writes.jsonl"
    shared_workspace_lock = threading.Lock()
    progress_log_lock = threading.Lock()

    parent_pool: list[dict[str, Any]] = []

    existing_records: list[dict[str, Any]] = []
    if not args.no_resume:
        all_records = load_existing_run_records(runs_log_path)
        def _matches_run(rec: dict[str, Any]) -> bool:
            if not (
                rec.get("benchmark", "supergpqa") == args.benchmark
                and rec.get("model") == args.model
                and rec.get("seed") == args.seed
                and rec.get("generation") == args.generation
                and rec.get("bootstrap_rollout_count", rec.get("num_rollouts"))
                == args.num_rollouts
                and _worker_backend_resume_compatible(rec, args)
            ):
                return False
            if args.benchmark != "supergpqa":
                if args.benchmark == "open-ended":
                    return rec.get("open_ended_task_sha256") == (
                        open_ended_task.sha256 if open_ended_task is not None else None
                    )
                return True
            return (
                rec.get("dataset_name") == args.dataset_name
                and rec.get("split") == args.split
                and rec.get("config_name") == args.config_name
                and rec.get("difficulty_filter") == difficulty_filter_payload
            )

        existing_records = [rec for rec in all_records if _matches_run(rec)]

    if not args.no_resume and existing_records:
        parent_pool = load_parent_pool(parent_pool_path)
        preliminary_by_task: dict[int, dict[int, dict[str, Any]]] = {}
        for record in existing_records:
            task_idx = record.get("task_index")
            rollout_idx = record.get("rollout_index")
            if isinstance(task_idx, int) and isinstance(rollout_idx, int) and rollout_idx >= 0:
                preliminary_by_task.setdefault(task_idx, {}).setdefault(rollout_idx, record)
        partial_tasks: set[int] = set()
        for task_idx, per_task in preliminary_by_task.items():
            counts: list[int] = []
            for record in per_task.values():
                try:
                    count = int(
                        record.get(
                            "task_rollout_count",
                            record.get("scheduled_rollout_count", args.num_rollouts),
                        )
                    )
                except (TypeError, ValueError):
                    continue
                if count > 0:
                    counts.append(count)
            if len(per_task) < (max(counts) if counts else args.num_rollouts):
                partial_tasks.add(task_idx)

        def _partial_prompt_matches(record: dict[str, Any]) -> bool:
            if record.get("task_index") not in partial_tasks or args.worker_backend != "opencode":
                return True
            rollout_idx = record.get("rollout_index")
            inherited_prompt = None
            if record.get("bootstrap_seed_used") is not True:
                if not isinstance(rollout_idx, int) or not 0 <= rollout_idx < len(parent_pool):
                    return False
                inherited_prompt = _slot_prompt(parent_pool[rollout_idx])
                if inherited_prompt is None:
                    return False
            return _worker_backend_resume_compatible(
                record,
                args,
                effective_initial_prompt=inherited_prompt,
                require_effective_prompt=True,
            )

        existing_records = [record for record in existing_records if _partial_prompt_matches(record)]

    existing_by_task: dict[int, dict[int, dict[str, Any]]] = {}
    for rec in existing_records:
        task_idx = rec.get("task_index")
        rollout_idx = rec.get("rollout_index")
        if not isinstance(task_idx, int) or not isinstance(rollout_idx, int):
            continue
        if rollout_idx < 0:
            continue
        per_task = existing_by_task.setdefault(task_idx, {})
        existing = per_task.get(rollout_idx)
        if existing is None:
            per_task[rollout_idx] = rec

    def _rollout_username(rollout_index: int) -> str:
        return f"rollout_user_{rollout_index:03d}"

    def _recorded_task_rollout_count(per_task: dict[int, dict[str, Any]]) -> int | None:
        counts: list[int] = []
        for rec in per_task.values():
            raw_count = rec.get("task_rollout_count", rec.get("scheduled_rollout_count"))
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            if count > 0:
                counts.append(count)
        return max(counts) if counts else None

    def _next_step_task_index() -> int:
        eligible_indices = [idx for idx in existing_by_task if idx >= args.start_task_index]
        for idx in sorted(eligible_indices):
            per_task = existing_by_task[idx]
            expected_count = _recorded_task_rollout_count(per_task) or args.num_rollouts
            if len(per_task) < expected_count:
                return idx
        if eligible_indices:
            return max(eligible_indices) + 1
        return args.start_task_index

    benchmark_driver = _create_benchmark_driver(
        args,
        arc_benchmark_state_path=arc_benchmark_state_path,
        problem_queue_path=problem_queue_path,
        task_store_dir=task_store_dir,
        dataset_cache_dir=dataset_cache_dir,
        existing_records=existing_records,
        open_ended_task=open_ended_task,
        open_ended_state_dir=open_ended_state_dir,
    )
    active_drivers.append(benchmark_driver)
    problem_start_index = _next_step_task_index() if args.step else args.start_task_index
    problem_batch_count = args.max_tasks if args.all_tasks and args.max_tasks is not None else 1
    scheduled_batches = [
        ScheduledBenchmarkBatch(
            iteration_index=index,
            scheduler_id=(
                f"open_ended_iteration_{index:06d}"
                if args.benchmark == "open-ended"
                else f"problem_pool_batch_{index:06d}"
            ),
        )
        for index in range(problem_start_index, problem_start_index + problem_batch_count)
    ]

    for scheduled_batch in scheduled_batches:
        task_index = scheduled_batch.iteration_index
        task_id = scheduled_batch.scheduler_id
        problem_uid = (
            None if args.benchmark == "open-ended" else scheduled_batch.scheduler_id
        )
        existing_task_records = existing_by_task.get(task_index, {})
        recorded_task_rollout_count = _recorded_task_rollout_count(existing_task_records)
        bootstrap_without_parent = not parent_pool
        task_rollout_count = (
            recorded_task_rollout_count
            if recorded_task_rollout_count is not None
            else (args.num_rollouts if bootstrap_without_parent else len(parent_pool))
        )
        if task_rollout_count <= 0:
            raise RuntimeError(
                f"No rollout population positions available for task_index={task_index}."
            )
        task_instance_uuids: dict[int, str] = {}
        for rollout_index in range(task_rollout_count):
            if rollout_index in existing_task_records:
                task_instance_uuids[rollout_index] = str(
                    existing_task_records[rollout_index].get("instance_uuid") or new_instance_uuid()
                )
                continue
            if rollout_index < len(parent_pool):
                task_instance_uuids[rollout_index] = (
                    _slot_child_instance_uuid(parent_pool[rollout_index]) or new_instance_uuid()
                )
                continue
            task_instance_uuids[rollout_index] = new_instance_uuid()
        live_peer_instances = [
            {
                "rollout_index": rollout_index,
                "rollout_username": _rollout_username(rollout_index),
                "instance_uuid": task_instance_uuids[rollout_index],
            }
            for rollout_index in range(task_rollout_count)
            if rollout_index not in existing_task_records
        ]
        spawn_slots_path = rollout_root / (
            f"{task_index:06d}_{_sanitize_for_path(task_id)}_spawn_slots.json"
        )
        spawn_slots_dir = rollout_root / (
            f"{task_index:06d}_{_sanitize_for_path(task_id)}_next_iteration"
        )
        if len(existing_task_records) >= task_rollout_count:
            continue

        benchmark_readme_path = shared_workspace_dir / BENCHMARK_README_FILENAME
        prepared_benchmark_batch = benchmark_driver.prepare_batch(
            task_index,
            shared_workspace_dir,
        )
        has_problem_pool = prepared_benchmark_batch.metadata.get("has_problem_pool") is not False
        problem_pool_json_path = (
            shared_workspace_dir / "problem_pool.json" if has_problem_pool else None
        )
        problem_pool_markdown_path = (
            shared_workspace_dir / "problem_pool.md" if has_problem_pool else None
        )
        if prepared_benchmark_batch.item_count <= 0 and has_problem_pool:
            if args.benchmark == "arc-agi":
                raise RuntimeError(
                    "No ARC public environments are available for the rollout catalog."
                )
            raise RuntimeError("No unsolved problems are available for the rollout problem pool.")
        if not benchmark_readme_path.is_file():
            raise RuntimeError("benchmark driver did not provide shared benchmark instructions")
        problem_pool_count = prepared_benchmark_batch.item_count if has_problem_pool else None
        batch_reporting = (
            {
                "configured_problem_pool_size": args.problem_pool_size,
                "problem_pool_count": problem_pool_count,
            }
            if has_problem_pool
            else {
                "evaluation": "unconfigured",
                "open_ended_task_sha256": prepared_benchmark_batch.metadata.get(
                    "task_sha256"
                ),
            }
        )

        def _run_one_rollout(rollout_index: int) -> RolloutResult:
            existing = existing_task_records.get(rollout_index)
            if existing is not None:
                raise RuntimeError(f"rollout {rollout_index} already exists and should not have been submitted")

            rollout_username = _rollout_username(rollout_index)
            sampled_parent: dict[str, Any] | None = (
                parent_pool[rollout_index] if rollout_index < len(parent_pool) else None
            )
            bootstrap_reinitialized = _is_reinitialized_bootstrap_slot(sampled_parent)
            instance_uuid = task_instance_uuids[rollout_index]
            rollout_control_dir = runtime_root / "logs" / "rollout_control" / instance_uuid
            rollout_state_dir = runtime_root / "logs" / "rollout_state" / instance_uuid
            opencode_mcp_control_dir = rollout_control_dir / "mcp"
            rollout_live_peer_instances = [
                peer
                for peer in live_peer_instances
                if peer.get("instance_uuid") != instance_uuid
            ]
            started_at = time.monotonic()

            def _progress(event: str, **fields: Any) -> None:
                record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                    "generation": args.generation,
                    "seed": args.seed,
                    "task_index": task_index,
                    "rollout_index": rollout_index,
                    "rollout_username": rollout_username,
                    "task_id": task_id,
                    **({"problem_uid": problem_uid} if has_problem_pool else {}),
                    **batch_reporting,
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    **fields,
                }
                append_progress_log(progress_log_path, progress_log_lock, record)

            if sampled_parent is None and not bootstrap_without_parent:
                raise RuntimeError(
                    "No spawned child slot available for non-bootstrap rollout; "
                    f"task_index={task_index} rollout_index={rollout_index}"
                )
            _progress(
                "rollout_started",
                instance_uuid=instance_uuid,
                parent_slot_dir=(
                    sampled_parent.get("slot_dir")
                    if sampled_parent and not bootstrap_reinitialized
                    else None
                ),
                parent_workspace_dir=(
                    sampled_parent.get("workspace_dir")
                    if sampled_parent and not bootstrap_reinitialized
                    else None
                ),
                bootstrap_seed_dir=(
                    str(bootstrap_seed_dir)
                    if sampled_parent is None or bootstrap_reinitialized
                    else None
                ),
                bootstrap_reinitialized=bootstrap_reinitialized,
            )
            archive_worktree = create_archive_worktree(
                archive_repo_dir=archive_repo_dir,
                worktree_root=archive_worktree_root,
                branch=f"rollout/{task_index:06d}-{rollout_index:03d}-{_sanitize_for_path(task_id)}",
                git_lock=archive_git_lock,
            )
            archive_result: dict[str, Any] = {}
            _progress(
                "archive_worktree_created",
                archive_worktree_dir=str(archive_worktree.path),
                archive_branch=archive_worktree.branch,
            )

            temp_dir = fixed_temp_dir / f"{task_index:06d}" / f"rollout_{rollout_index:03d}"
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir.mkdir(parents=True, exist_ok=True)
            bootstrap_seed_used = sampled_parent is None or bootstrap_reinitialized
            rollout_initial_prompt = (
                args.opencode_initial_prompt
                if args.worker_backend == "opencode"
                else args.codex_initial_prompt
            )
            if sampled_parent is not None and not bootstrap_reinitialized:
                parent_prompt = _slot_prompt(sampled_parent)
                if parent_prompt is None:
                    raise RuntimeError(
                        "Spawned child slot is missing prompt metadata; "
                        f"task_index={task_index} rollout_index={rollout_index}"
                    )
                rollout_initial_prompt = parent_prompt
                parent_workspace_dir = _slot_workspace_dir(sampled_parent)
                if parent_workspace_dir is not None:
                    if not parent_workspace_dir.is_dir():
                        raise RuntimeError(f"Spawned child workspace is missing: {parent_workspace_dir}")
                    copy_seed_workspace(parent_workspace_dir, temp_dir, consume=True)
                    _progress(
                        "parent_workspace_consumed",
                        parent_workspace_dir=str(parent_workspace_dir),
                    )
            else:
                if not bootstrap_seed_dir.exists():
                    raise RuntimeError(f"Bootstrap seed directory does not exist: {bootstrap_seed_dir}")
                copy_seed_workspace(bootstrap_seed_dir, temp_dir)
                if args.worker_backend != "opencode":
                    rollout_initial_prompt = _format_bootstrap_seed_prompt(
                        bootstrap_seed_dir
                    )

            seed_output_dir = temp_dir / "seed_output"
            seed_output_dir.mkdir(parents=True, exist_ok=True)
            archive_link = temp_dir / "archive"
            shared_workspace_link = temp_dir / "shared_workspace"
            _replace_with_symlink(archive_link, archive_worktree.path)
            _replace_with_symlink(shared_workspace_link, shared_workspace_dir)

            runtime_file = temp_dir / "runtime.md"
            codex_base_instructions = (
                resolve_codex_base_instructions(args.codex_base_instructions_mode)
                if args.worker_backend == "codex"
                else None
            )
            opencode_system_instructions = (
                resolve_opencode_system_instructions(
                    args.opencode_base_instructions_mode
                )
                if args.worker_backend == "opencode"
                else None
            )
            continuation_context = _make_continuation_context(
                worker_backend=args.worker_backend,
                model=args.model,
                workdir=temp_dir,
                seed_output_dir=seed_output_dir,
                archive_repo_dir=archive_worktree.path,
                shared_workspace_dir=shared_workspace_dir,
                shared_workspace_write_log=shared_workspace_write_log,
                spawn_slots_path=spawn_slots_path,
                spawn_slots_dir=spawn_slots_dir,
                population_size=args.num_rollouts,
                live_peer_instances=rollout_live_peer_instances,
                progress_log_path=progress_log_path,
                generation=args.generation,
                seed=args.seed,
                task_index=task_index,
                task_id=task_id,
                rollout_index=rollout_index,
                rollout_username=rollout_username,
                instance_uuid=instance_uuid,
                worker_timeout_seconds=args.worker_timeout_seconds,
                bash_timeout_seconds=args.bash_timeout_seconds,
                openrouter_max_retries=args.openrouter_max_retries,
                codex_runner_bin=codex_runner_bin,
                codex_home=codex_home,
                codex_sandbox_mode=args.codex_sandbox_mode,
                codex_initial_prompt=args.codex_initial_prompt,
                codex_base_instructions=codex_base_instructions,
            )
            planned_context_path = (
                opencode_mcp_control_dir / CONTINUATION_CONTEXT_FILENAME
                if args.worker_backend == "opencode"
                else rollout_control_dir / CONTINUATION_CONTEXT_FILENAME
            )
            rollout_benchmark = benchmark_driver.prepare_rollout(
                prepared_benchmark_batch,
                backend=args.worker_backend,
                context={
                    **continuation_context,
                    "continuation_context_path": str(planned_context_path),
                    "rollout_state_dir": str(rollout_state_dir),
                    **(
                        {"benchmark_events_path": str(benchmark_events_path)}
                        if benchmark_events_path is not None
                        else {}
                    ),
                },
            )
            continuation_context = rollout_benchmark.context
            runtime_file.write_text(
                _format_runtime_markdown(
                    instance_uuid=instance_uuid,
                    parent_instance_uuid=(
                        str(sampled_parent.get("parent_instance_uuid"))
                        if (
                            sampled_parent
                            and not bootstrap_reinitialized
                            and sampled_parent.get("parent_instance_uuid")
                        )
                        else None
                    ),
                    child_slot_index=rollout_index,
                    problem_pool_json_path=(
                        "shared_workspace/problem_pool.json" if has_problem_pool else None
                    ),
                    problem_pool_markdown_path=(
                        "shared_workspace/problem_pool.md" if has_problem_pool else None
                    ),
                    configured_problem_pool_size=args.problem_pool_size,
                    problem_pool_count=problem_pool_count,
                    live_peer_instances=rollout_live_peer_instances,
                    has_problem_pool=has_problem_pool,
                ),
                encoding="utf-8",
            )
            continuation_context_path = (
                _write_continuation_context(continuation_context, rollout_control_dir)
                if args.worker_backend in {"codex", "opencode"}
                else None
            )
            opencode_mcp_context_path = (
                _write_continuation_context(
                    continuation_context,
                    opencode_mcp_control_dir,
                )
                if args.worker_backend == "opencode"
                else None
            )
            _progress(
                "workspace_prepared",
                working_directory=str(temp_dir),
                runtime_file=str(runtime_file),
                benchmark_readme=str(benchmark_readme_path),
                problem_queue_path=(
                    str(problem_queue_path) if args.benchmark == "supergpqa" else None
                ),
                **(
                    {
                        "problem_pool_json_path": str(problem_pool_json_path),
                        "problem_pool_markdown_path": str(problem_pool_markdown_path),
                    }
                    if has_problem_pool
                    else {}
                ),
                **batch_reporting,
                seed_output_dir=str(seed_output_dir),
                rollout_control_dir=(
                    str(rollout_control_dir)
                    if args.worker_backend in {"codex", "opencode"}
                    else None
                ),
                rollout_state_dir=str(rollout_state_dir),
                continuation_context_path=(
                    str(continuation_context_path) if continuation_context_path is not None else None
                ),
                codex_base_instructions_mode=(
                    args.codex_base_instructions_mode if args.worker_backend == "codex" else None
                ),
                codex_base_instructions_chars=(
                    len(codex_base_instructions) if codex_base_instructions is not None else None
                ),
                opencode_base_instructions_mode=(
                    args.opencode_base_instructions_mode
                    if args.worker_backend == "opencode"
                    else None
                ),
                opencode_system_instructions_chars=(
                    len(opencode_system_instructions)
                    if opencode_system_instructions is not None
                    else None
                ),
                opencode_system_instructions_sha256=(
                    text_sha256(opencode_system_instructions)
                    if args.worker_backend == "opencode"
                    else None
                ),
                opencode_effective_initial_prompt_sha256=(
                    text_sha256(rollout_initial_prompt)
                    if args.worker_backend == "opencode"
                    else None
                ),
                bootstrap_seed_used=bootstrap_seed_used,
                bootstrap_seed_embedded=False,
                rollout_initial_prompt_chars=len(rollout_initial_prompt),
            )

            try:
                try:
                    if args.worker_backend == "codex":
                        if codex_runner_bin is None:
                            raise RuntimeError("Codex runner binary was not initialized.")
                        worker_result = run_codex_worker(
                            runner_bin=codex_runner_bin,
                            model=args.model,
                            workdir=temp_dir,
                            control_dir=rollout_control_dir,
                            worker_state_dir=rollout_state_dir,
                            codex_home=codex_home,
                            seed_output_dir=seed_output_dir,
                            archive_repo_dir=archive_worktree.path,
                            archive_git_dir=archive_repo_dir / ".git",
                            shared_workspace_dir=shared_workspace_dir,
                            rollout_username=rollout_username,
                            timeout_seconds=args.worker_timeout_seconds,
                            sandbox_mode=args.codex_sandbox_mode,
                            initial_user_text=rollout_initial_prompt,
                            base_instructions=codex_base_instructions,
                            continuation_context_path=continuation_context_path,
                            benchmark_mcp_servers=rollout_benchmark.mcp_servers,
                            sensitive_mcp_tools=rollout_benchmark.sensitive_mcp_tools,
                            progress_callback=_progress,
                        )
                    elif args.worker_backend == "opencode":
                        if (
                            opencode_worker_script is None
                            or opencode_bun_bin is None
                            or opencode_bin is None
                        ):
                            raise RuntimeError(
                                "OpenCode worker, Bun, and CLI were not initialized."
                            )
                        worker_result = run_opencode_worker(
                            worker_script=opencode_worker_script,
                            bun_bin=opencode_bun_bin,
                            opencode_bin=opencode_bin,
                            model=args.model,
                            workdir=temp_dir,
                            control_dir=rollout_control_dir,
                            worker_state_dir=rollout_state_dir,
                            timeout_seconds=args.worker_timeout_seconds,
                            initial_user_text=rollout_initial_prompt,
                            system_instructions=opencode_system_instructions,
                            continuation_context_path=continuation_context_path,
                            benchmark_mcp_servers=rollout_benchmark.mcp_servers,
                            sensitive_mcp_tools=rollout_benchmark.sensitive_mcp_tools,
                            auth_file=opencode_auth_file,
                            agent=args.opencode_agent,
                            variant=args.opencode_variant,
                            allowed_versions=opencode_allowed_versions,
                            allowed_bun_versions=opencode_allowed_bun_versions,
                            startup_timeout_seconds=(
                                args.opencode_server_startup_timeout_seconds
                            ),
                            provider_env_names=opencode_provider_env_names,
                            provider_environment=opencode_provider_environment,
                            custom_provider=opencode_custom_provider,
                            sandbox_mode=(
                                "bubblewrap"
                                if args.opencode_sandbox_mode == "bubblewrap"
                                else "none"
                            ),
                            sandbox_network=args.opencode_network_mode,
                            bubblewrap_bin=opencode_bubblewrap_bin,
                            sandbox_read_only_roots=tuple(
                                path
                                for path in (
                                    seed_output_dir,
                                )
                                if path.exists()
                            ),
                            sandbox_read_only_mounts=opencode_credential_mounts,
                            sandbox_writable_roots=tuple(
                                path
                                for path in (
                                    archive_worktree.path,
                                    archive_repo_dir / ".git",
                                    shared_workspace_dir,
                                )
                                if path is not None and path.exists()
                            ),
                            sandbox_masked_paths=(
                                (DEFAULT_ENV_PATH,) if DEFAULT_ENV_PATH.is_file() else ()
                            ),
                            progress_callback=_progress,
                        )
                    else:
                        if api_key is None:
                            raise RuntimeError("OPENROUTER_API_KEY is required for the OpenRouter backend.")
                        worker_result = run_worker(
                            api_key=api_key,
                            model=args.model,
                            workdir=temp_dir,
                            seed_output_dir=seed_output_dir,
                            archive_repo_dir=archive_worktree.path,
                            shared_workspace_dir=shared_workspace_dir,
                            worker_state_dir=rollout_state_dir,
                            shared_workspace_write_log=shared_workspace_write_log,
                            shared_workspace_lock=shared_workspace_lock,
                            task_index=task_index,
                            task_id=task_id,
                            rollout_index=rollout_index,
                            rollout_username=rollout_username,
                            timeout_seconds=args.worker_timeout_seconds,
                            bash_timeout_seconds=args.bash_timeout_seconds,
                            openrouter_max_retries=args.openrouter_max_retries,
                            continuation_context=continuation_context,
                            benchmark_driver=benchmark_driver,
                            rollout_benchmark=rollout_benchmark,
                            initial_user_text=rollout_initial_prompt,
                            progress_callback=_progress,
                        )
                except BaseException as exc:
                    worker_result = WorkerResult(
                        final_text="",
                        status="error",
                        stop_reason=type(exc).__name__,
                        error_code=None,
                        error_message=str(exc),
                    )
                finally:
                    archive_result = finalize_archive_worktree(
                        archive_repo_dir=archive_repo_dir,
                        worktree=archive_worktree,
                        git_lock=archive_git_lock,
                    )
                    _progress("archive_finalized", **archive_result)
            except BaseException as exc:
                archive_result = {
                    **archive_result,
                    "archive_finalize_error": f"{type(exc).__name__}: {exc}",
                }
                worker_result = WorkerResult(
                    final_text="",
                    status="error",
                    stop_reason=type(exc).__name__,
                    error_code=None,
                    error_message=str(exc),
                )
            _progress(
                "worker_finished",
                worker_status=worker_result.status,
                worker_stop_reason=worker_result.stop_reason,
                worker_error_code=worker_result.error_code,
                worker_error_message=worker_result.error_message,
            )
            evaluation_unconfigured = (
                prepared_benchmark_batch.metadata.get("evaluation") == "unconfigured"
            )
            if evaluation_unconfigured:
                benchmark_outcome = None
            else:
                benchmark_outcome = benchmark_driver.collect_outcome(
                    prepared_benchmark_batch,
                    instance_uuid=instance_uuid,
                    context=continuation_context,
                )
                if benchmark_outcome is None:
                    raise RuntimeError(
                        "configured benchmark driver returned no evaluation outcome"
                    )
            if benchmark_outcome is None:
                outcome_item = None
                record_task_id = task_id
                record_problem_uid = None
                record_problem_task_index = None
                evaluation_record = {
                    "evaluation": "unconfigured",
                    "open_ended_task_sha256": prepared_benchmark_batch.metadata.get(
                        "task_sha256"
                    ),
                }
                _progress(
                    "evaluation_unconfigured",
                    evaluation="unconfigured",
                )
            else:
                outcome_item = benchmark_outcome.item_ref
                record_task_id = outcome_item.source_id if outcome_item is not None else None
                record_problem_uid = (
                    outcome_item.item_id
                    if outcome_item is not None
                    else benchmark_outcome.item_id
                )
                record_problem_task_index = (
                    outcome_item.item_index if outcome_item is not None else None
                )
                if not benchmark_outcome.attempted:
                    _progress(
                        "benchmark_not_attempted",
                        benchmark=args.benchmark,
                    )
                _progress(
                    "rollout_scored",
                    attempted=benchmark_outcome.attempted,
                    solved=benchmark_outcome.solved,
                    reward=benchmark_outcome.reward,
                    item=(outcome_item.to_metadata() if outcome_item is not None else None),
                    benchmark_metadata=benchmark_outcome.metadata,
                )
                evaluation_record = {
                    "solved": benchmark_outcome.solved,
                    "reward": benchmark_outcome.reward,
                    "benchmark_outcome_metadata": benchmark_outcome.metadata,
                }

            output_dir = persist_episode_outputs(
                temp_dir,
                outputs_dir,
                f"{record_task_id or 'unassigned'}_rollout_{rollout_index:03d}",
            )
            _progress("episode_persisted", output_path=str(output_dir))

            spawned_child_slots = _load_spawned_child_slots(
                spawn_slots_path,
                source_rollout_index=rollout_index,
            )
            consumed_source_workspaces = consume_spawn_source_workspaces(
                spawned_child_slots=spawned_child_slots,
                rollout_workdir=temp_dir,
            )
            if consumed_source_workspaces:
                _progress(
                    "source_workspaces_consumed",
                    consumed_source_workspace_dirs=consumed_source_workspaces,
                )
            next_child_slot = spawned_child_slots[0] if spawned_child_slots else None
            spawned_child_slot_indices: list[int] = []
            for slot in spawned_child_slots:
                try:
                    spawned_child_slot_indices.append(int(slot.get("slot_index")))
                except (TypeError, ValueError):
                    continue
            next_slot_dir = (
                str(next_child_slot.get("slot_dir"))
                if next_child_slot and next_child_slot.get("slot_dir")
                else None
            )
            next_workspace_dir = (
                str(next_child_slot.get("workspace_dir"))
                if next_child_slot and next_child_slot.get("workspace_dir")
                else None
            )
            child_prompt_viable = next_child_slot is not None and _slot_prompt(next_child_slot) is not None

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "benchmark": args.benchmark,
                "generation": args.generation,
                "seed": args.seed,
                "task_index": task_index,
                "rollout_index": rollout_index,
                "rollout_username": rollout_username,
                "instance_uuid": instance_uuid,
                "task_id": record_task_id,
                "scheduler_task_id": task_id,
                **(
                    {
                        "problem_uid": record_problem_uid,
                        "problem_task_index": record_problem_task_index,
                        "problem_assignment_key": _problem_assignment_key(
                            continuation_context
                        ),
                        "scheduler_problem_uid": problem_uid,
                    }
                    if has_problem_pool
                    else {}
                ),
                "parent_slot_dir": sampled_parent.get("slot_dir") if sampled_parent else None,
                "parent_workspace_dir": sampled_parent.get("workspace_dir") if sampled_parent else None,
                "bootstrap_seed_dir": (
                    str(bootstrap_seed_dir)
                    if sampled_parent is None or bootstrap_reinitialized
                    else None
                ),
                "bootstrap_reinitialized": bootstrap_reinitialized,
                "next_slot_dir": next_slot_dir,
                "next_workspace_dir": next_workspace_dir,
                "child_prompt_viable": child_prompt_viable,
                "spawned_child_slot_count": len(spawned_child_slots),
                "spawned_child_slot_indices": spawned_child_slot_indices,
                "consumed_source_workspace_dirs": consumed_source_workspaces,
                "reserved_child_slot_index": rollout_index,
                "successful_child_limit": 1,
                **(
                    {"benchmark_events_path": str(benchmark_events_path)}
                    if benchmark_events_path is not None
                    else {}
                ),
                "worker_status": worker_result.status,
                "worker_stop_reason": worker_result.stop_reason,
                "worker_error_code": worker_result.error_code,
                "worker_error_message": worker_result.error_message,
                "worker_backend": args.worker_backend,
                "worker_metadata": worker_result.metadata,
                **evaluation_record,
                "output_path": str(output_dir),
                "problem_queue_path": (
                    str(problem_queue_path) if args.benchmark == "supergpqa" else None
                ),
                **(
                    {
                        "problem_pool_json_path": str(problem_pool_json_path),
                        "problem_pool_markdown_path": str(problem_pool_markdown_path),
                    }
                    if has_problem_pool
                    else {}
                ),
                **batch_reporting,
                "shared_workspace_write_log": str(shared_workspace_write_log),
                "progress_log": str(progress_log_path),
                "dataset_name": args.dataset_name if args.benchmark == "supergpqa" else None,
                "split": args.split if args.benchmark == "supergpqa" else None,
                "difficulty_filter": (
                    difficulty_filter_payload if args.benchmark == "supergpqa" else None
                ),
                "model": args.model,
                "num_rollouts": args.num_rollouts,
                "bootstrap_rollout_count": args.num_rollouts,
                "task_rollout_count": task_rollout_count,
                "worker_timeout_seconds": args.worker_timeout_seconds,
                "bash_timeout_seconds": args.bash_timeout_seconds,
                "openrouter_max_retries": args.openrouter_max_retries,
                "codex_home": str(codex_home) if args.worker_backend == "codex" else None,
                "codex_runner_bin": str(codex_runner_bin) if codex_runner_bin is not None else None,
                "codex_sandbox_mode": args.codex_sandbox_mode if args.worker_backend == "codex" else None,
                "codex_initial_prompt": args.codex_initial_prompt if args.worker_backend == "codex" else None,
                "codex_base_instructions_mode": (
                    args.codex_base_instructions_mode if args.worker_backend == "codex" else None
                ),
                "codex_base_instructions_chars": (
                    len(codex_base_instructions)
                    if args.worker_backend == "codex" and codex_base_instructions is not None
                    else None
                ),
                "opencode_bin": (
                    str(opencode_bin) if args.worker_backend == "opencode" else None
                ),
                "opencode_runner_bin": (
                    str(opencode_worker_script)
                    if args.worker_backend == "opencode"
                    and opencode_worker_script is not None
                    else None
                ),
                "opencode_worker_script": (
                    str(opencode_worker_script)
                    if args.worker_backend == "opencode"
                    and opencode_worker_script is not None
                    else None
                ),
                "opencode_bun_bin": (
                    str(opencode_bun_bin)
                    if args.worker_backend == "opencode"
                    and opencode_bun_bin is not None
                    else None
                ),
                "opencode_base_instructions_mode": (
                    args.opencode_base_instructions_mode
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_system_instructions_chars": (
                    len(opencode_system_instructions)
                    if args.worker_backend == "opencode"
                    and opencode_system_instructions is not None
                    else None
                ),
                "opencode_allowed_versions": (
                    list(opencode_allowed_versions)
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_allowed_bun_versions": (
                    list(opencode_allowed_bun_versions)
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_runtime_version": opencode_runtime_version,
                "opencode_bin_sha256": opencode_bin_sha256,
                "opencode_bun_version": opencode_bun_version,
                "opencode_bun_sha256": opencode_bun_sha256,
                "opencode_worker_sha256": opencode_worker_sha256,
                "opencode_python_sha256": opencode_python_sha256,
                "opencode_auth_sha256": opencode_auth_sha256,
                "opencode_provider_env_sha256": opencode_provider_env_sha256,
                "opencode_custom_provider": (
                    opencode_custom_provider
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_custom_provider_sha256": (
                    opencode_custom_provider_sha256
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_server_startup_timeout_seconds": (
                    args.opencode_server_startup_timeout_seconds
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_worker_timeout_seconds": (
                    args.worker_timeout_seconds
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_sandbox_mode": (
                    args.opencode_sandbox_mode if args.worker_backend == "opencode" else None
                ),
                "opencode_network_mode": (
                    args.opencode_network_mode if args.worker_backend == "opencode" else None
                ),
                "opencode_bubblewrap_bin": (
                    str(opencode_bubblewrap_bin)
                    if args.worker_backend == "opencode"
                    and opencode_bubblewrap_bin is not None
                    else None
                ),
                "opencode_bubblewrap_version": opencode_bubblewrap_version,
                "opencode_bubblewrap_sha256": opencode_bubblewrap_sha256,
                "opencode_system_instructions_sha256": (
                    text_sha256(opencode_system_instructions)
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_configured_initial_prompt_sha256": (
                    opencode_configured_initial_prompt_sha256
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_effective_initial_prompt_sha256": (
                    text_sha256(rollout_initial_prompt)
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_provider_env_names": (
                    list(opencode_provider_env_names)
                    if args.worker_backend == "opencode"
                    else None
                ),
                "opencode_agent": (
                    args.opencode_agent if args.worker_backend == "opencode" else None
                ),
                "opencode_variant": (
                    args.opencode_variant if args.worker_backend == "opencode" else None
                ),
                "opencode_auth_source": (
                    "file"
                    if args.worker_backend == "opencode" and opencode_auth_file is not None
                    else "environment" if args.worker_backend == "opencode" else None
                ),
                "bootstrap_seed_used": bootstrap_seed_used,
                "bootstrap_seed_embedded": False,
                "rollout_initial_prompt_chars": len(rollout_initial_prompt),
                "config_name": args.config_name if args.benchmark == "supergpqa" else None,
                "runtime_root": str(runtime_root),
                "dataset_cache_dir": (
                    str(dataset_cache_dir) if args.benchmark == "supergpqa" else None
                ),
                **archive_result,
            }
            if benchmark_outcome is not None:
                record.update(benchmark_outcome.run_record)
                summary = (
                    f"gen={args.generation} seed={args.seed} task_index={task_index} rollout_index={rollout_index} "
                    f"rollout_username={rollout_username} task_id={record_task_id or 'unassigned'} "
                    f"benchmark_attempted={benchmark_outcome.attempted} "
                    f"benchmark_solved={benchmark_outcome.solved} output={output_dir}"
                )
            else:
                summary = (
                    f"gen={args.generation} seed={args.seed} task_index={task_index} rollout_index={rollout_index} "
                    f"rollout_username={rollout_username} task_id={record_task_id} "
                    f"evaluation=unconfigured output={output_dir}"
                )
            if worker_result.status == "error":
                summary += f" error={worker_result.stop_reason}"
            return RolloutResult(
                rollout_index=rollout_index,
                record=record,
                successful_dir=Path(next_slot_dir) if next_slot_dir is not None else None,
                summary=summary,
                error=worker_result.error_message if worker_result.status == "error" else None,
                benchmark_outcome=benchmark_outcome,
            )

        missing_rollout_indices: list[int] = []
        for rollout_index in range(task_rollout_count):
            existing = existing_task_records.get(rollout_index)
            if existing is not None:
                continue
            missing_rollout_indices.append(rollout_index)

        shared_snapshot = _snapshot_workspace_files(shared_workspace_dir)
        results: list[RolloutResult] = []
        if missing_rollout_indices:
            with ThreadPoolExecutor(max_workers=len(missing_rollout_indices)) as executor:
                futures = {
                    executor.submit(_run_one_rollout, rollout_index): rollout_index
                    for rollout_index in missing_rollout_indices
                }
                pending = set(futures)
                while pending:
                    done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        rollout_index = futures[future]
                        try:
                            results.append(future.result())
                        except BaseException as exc:
                            discard_archive_worktree(
                                archive_repo_dir=archive_repo_dir,
                                worktree_root=archive_worktree_root,
                                branch=(
                                    f"rollout/{task_index:06d}-{rollout_index:03d}-"
                                    f"{_sanitize_for_path(task_id)}"
                                ),
                                git_lock=archive_git_lock,
                            )
                            append_progress_log(
                                progress_log_path,
                                progress_log_lock,
                                {
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "event": "rollout_future_failed",
                                    "generation": args.generation,
                                    "seed": args.seed,
                                    "task_index": task_index,
                                    "rollout_index": rollout_index,
                                    "rollout_username": _rollout_username(rollout_index),
                                    "task_id": task_id,
                                    **({"problem_uid": problem_uid} if has_problem_pool else {}),
                                    **batch_reporting,
                                    "worker_status": "error",
                                    "worker_stop_reason": type(exc).__name__,
                                    "worker_error_message": str(exc),
                                },
                            )
                            results.append(
                                RolloutResult(
                                    rollout_index=rollout_index,
                                    record={
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "benchmark": args.benchmark,
                                        "generation": args.generation,
                                        "seed": args.seed,
                                        "task_index": task_index,
                                        "rollout_index": rollout_index,
                                        "rollout_username": _rollout_username(rollout_index),
                                        "task_id": task_id,
                                        **(
                                            {"problem_uid": problem_uid}
                                            if has_problem_pool
                                            else {}
                                        ),
                                        "parent_slot_dir": None,
                                        "parent_workspace_dir": None,
                                        "bootstrap_seed_dir": str(bootstrap_seed_dir),
                                        "next_slot_dir": None,
                                        "next_workspace_dir": None,
                                        "child_prompt_viable": False,
                                        "reserved_child_slot_index": rollout_index,
                                        "successful_child_limit": 1,
                                        "worker_status": "error",
                                        "worker_stop_reason": type(exc).__name__,
                                        "worker_error_code": None,
                                        "worker_error_message": str(exc),
                                        "worker_backend": args.worker_backend,
                                        "worker_metadata": None,
                                        **(
                                            {
                                                "evaluation": "unconfigured",
                                                "open_ended_task_sha256": (
                                                    prepared_benchmark_batch.metadata.get(
                                                        "task_sha256"
                                                    )
                                                ),
                                            }
                                            if args.benchmark == "open-ended"
                                            else {"solved": False, "reward": 0.0}
                                        ),
                                        "output_path": None,
                                        "problem_queue_path": (
                                            str(problem_queue_path)
                                            if args.benchmark == "supergpqa"
                                            else None
                                        ),
                                        **batch_reporting,
                                        "shared_workspace_write_log": str(shared_workspace_write_log),
                                        "progress_log": str(progress_log_path),
                                        "dataset_name": (
                                            args.dataset_name
                                            if args.benchmark == "supergpqa"
                                            else None
                                        ),
                                        "split": (
                                            args.split if args.benchmark == "supergpqa" else None
                                        ),
                                        "difficulty_filter": (
                                            difficulty_filter_payload
                                            if args.benchmark == "supergpqa"
                                            else None
                                        ),
                                        "model": args.model,
                                        "num_rollouts": args.num_rollouts,
                                        "bootstrap_rollout_count": args.num_rollouts,
                                        "task_rollout_count": task_rollout_count,
                                        "worker_timeout_seconds": args.worker_timeout_seconds,
                                        "bash_timeout_seconds": args.bash_timeout_seconds,
                                        "openrouter_max_retries": args.openrouter_max_retries,
                                        "codex_home": str(codex_home) if args.worker_backend == "codex" else None,
                                        "codex_runner_bin": str(codex_runner_bin) if codex_runner_bin is not None else None,
                                        "codex_sandbox_mode": args.codex_sandbox_mode if args.worker_backend == "codex" else None,
                                        "codex_initial_prompt": args.codex_initial_prompt if args.worker_backend == "codex" else None,
                                        "codex_base_instructions_mode": (
                                            args.codex_base_instructions_mode
                                            if args.worker_backend == "codex"
                                            else None
                                        ),
                                        "codex_base_instructions_chars": None,
                                        "opencode_bin": (
                                            str(opencode_bin)
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_runner_bin": (
                                            str(opencode_worker_script)
                                            if args.worker_backend == "opencode"
                                            and opencode_worker_script is not None
                                            else None
                                        ),
                                        "opencode_worker_script": (
                                            str(opencode_worker_script)
                                            if args.worker_backend == "opencode"
                                            and opencode_worker_script is not None
                                            else None
                                        ),
                                        "opencode_bun_bin": (
                                            str(opencode_bun_bin)
                                            if args.worker_backend == "opencode"
                                            and opencode_bun_bin is not None
                                            else None
                                        ),
                                        "opencode_base_instructions_mode": (
                                            args.opencode_base_instructions_mode
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_system_instructions_chars": None,
                                        "opencode_allowed_versions": (
                                            list(opencode_allowed_versions)
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_allowed_bun_versions": (
                                            list(opencode_allowed_bun_versions)
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_runtime_version": opencode_runtime_version,
                                        "opencode_bin_sha256": opencode_bin_sha256,
                                        "opencode_bun_version": opencode_bun_version,
                                        "opencode_bun_sha256": opencode_bun_sha256,
                                        "opencode_worker_sha256": opencode_worker_sha256,
                                        "opencode_auth_sha256": opencode_auth_sha256,
                                        "opencode_provider_env_sha256": (
                                            opencode_provider_env_sha256
                                        ),
                                        "opencode_custom_provider": (
                                            opencode_custom_provider
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_custom_provider_sha256": (
                                            opencode_custom_provider_sha256
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_server_startup_timeout_seconds": (
                                            args.opencode_server_startup_timeout_seconds
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_sandbox_mode": (
                                            args.opencode_sandbox_mode
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_network_mode": (
                                            args.opencode_network_mode
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_provider_env_names": (
                                            list(opencode_provider_env_names)
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_agent": (
                                            args.opencode_agent
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_variant": (
                                            args.opencode_variant
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "opencode_auth_source": (
                                            "file"
                                            if args.worker_backend == "opencode"
                                            and opencode_auth_file is not None
                                            else "environment"
                                            if args.worker_backend == "opencode"
                                            else None
                                        ),
                                        "config_name": (
                                            args.config_name
                                            if args.benchmark == "supergpqa"
                                            else None
                                        ),
                                        "runtime_root": str(runtime_root),
                                        "dataset_cache_dir": (
                                            str(dataset_cache_dir)
                                            if args.benchmark == "supergpqa"
                                            else None
                                        ),
                                        **(
                                            {}
                                            if args.benchmark == "open-ended"
                                            else
                                            {
                                                "submitted_uuid": None,
                                                "reported_problem_uid": None,
                                                "reported_task_id": None,
                                                "private_problem_path": None,
                                            }
                                            if args.benchmark == "supergpqa"
                                            else {"benchmark_item": None}
                                        ),
                                    },
                                    successful_dir=None,
                                    summary=(
                                        f"gen={args.generation} seed={args.seed} task_index={task_index} "
                                        f"rollout_index={rollout_index} rollout_username={_rollout_username(rollout_index)} "
                                        f"task_id={task_id} "
                                        + (
                                            "evaluation=unconfigured "
                                            if args.benchmark == "open-ended"
                                            else "solved=False "
                                        )
                                        + f"output=None error={type(exc).__name__}"
                                    ),
                                    error=str(exc),
                                )
                            )
        _cleanup_rollout_shared_writes(shared_workspace_dir, shared_snapshot)

        for result in sorted(results, key=lambda item: item.rollout_index):
            append_run_log(runs_log_path, result.record)
            print(result.summary)

        batch_outcomes = [
            result.benchmark_outcome
            for result in results
            if result.benchmark_outcome is not None
        ]
        benchmark_finalization = (
            benchmark_driver.finalize_batch(prepared_benchmark_batch, batch_outcomes)
            if (
                prepared_benchmark_batch is not None
                and prepared_benchmark_batch.metadata.get("evaluation") != "unconfigured"
            )
            else {}
        )
        if benchmark_finalization:
            append_progress_log(
                progress_log_path,
                progress_log_lock,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "benchmark_batch_finalized",
                    "generation": args.generation,
                    "seed": args.seed,
                    "task_index": task_index,
                    "task_id": task_id,
                    "problem_uid": problem_uid,
                    "configured_problem_pool_size": args.problem_pool_size,
                    "problem_pool_count": problem_pool_count,
                    "benchmark_finalization": benchmark_finalization,
                },
            )

        spawned_child_slots = _load_spawned_child_parent_slots(spawn_slots_path)
        parent_pool, reinitialized_bootstrap_count = _refill_parent_pool_with_bootstrap_slots(
            spawned_child_slots,
            target_count=args.num_rollouts,
        )
        save_parent_pool(parent_pool_path, parent_pool)
        append_progress_log(
            progress_log_path,
            progress_log_lock,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "parent_pool_finalized",
                "generation": args.generation,
                "seed": args.seed,
                "task_index": task_index,
                "task_id": task_id,
                "problem_uid": problem_uid,
                "population_size": args.num_rollouts,
                "spawned_child_slot_count": len(spawned_child_slots),
                "reinitialized_bootstrap_slot_count": reinitialized_bootstrap_count,
                "parent_pool_count": len(parent_pool),
                "parent_pool_path": str(parent_pool_path),
            },
        )

        failed_results = [result for result in results if result.error]
        if failed_results:
            details = "; ".join(
                f"rollout {result.rollout_index}: {result.error}"
                for result in sorted(failed_results, key=lambda item: item.rollout_index)
            )
            append_progress_log(
                progress_log_path,
                progress_log_lock,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "rollout_errors_detected",
                    "generation": args.generation,
                    "seed": args.seed,
                    "task_index": task_index,
                    "task_id": task_id,
                    "problem_uid": problem_uid,
                    "failed_rollout_count": len(failed_results),
                    "fatal": args.fail_on_rollout_error,
                    "failed_rollout_indices": [
                        result.rollout_index
                        for result in sorted(failed_results, key=lambda item: item.rollout_index)
                    ],
                    "details": details,
                    "parent_pool_path": str(parent_pool_path),
                },
            )
            if args.fail_on_rollout_error:
                raise RuntimeError(f"One or more rollouts failed after logging results: {details}")
            print(f"warning: one or more rollouts failed after logging results: {details}")

def main() -> None:
    active_drivers: list[BenchmarkDriver] = []
    try:
        _run_main(active_drivers)
    finally:
        for driver in reversed(active_drivers):
            driver.close()


def run_child_tool_handler(context_path: Path) -> None:
    """Entrypoint used by the Codex runner to execute main-loop dynamic tools."""
    try:
        load_dotenv()
        context = json.loads(context_path.read_text(encoding="utf-8"))
        raw_payload = sys.stdin.read()
        payload = json.loads(raw_payload) if raw_payload.strip() else {}
        if not isinstance(context, dict) or not isinstance(payload, dict):
            raise ValueError("handler context and payload must be JSON objects")
        tool = payload.get("tool")
        raw_args = payload.get("arguments")
        args = raw_args if isinstance(raw_args, dict) else {}
        if tool == "spawn_child":
            result = _spawn_child_continuation(
                context=context,
                args=args,
            )
        else:
            result = _spawn_failure(
                f"unsupported dynamic tool: {tool}",
                error_code="unsupported_dynamic_tool",
                retryable=True,
            )
    except BaseException as exc:
        result = _spawn_failure(
            f"{type(exc).__name__}: {exc}",
            error_code="spawn_child_handler_failed",
            retryable=True,
        )

    result = {
        **result,
        "success": bool(result.get("success")),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child-tool-handler":
        run_child_tool_handler(Path(sys.argv[2]).expanduser().resolve())
    else:
        main()

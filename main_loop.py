#!/usr/bin/env python3
"""Minimal RLVR episode loop.

Flow:
1) Sample one task from a Hugging Face RLVR-style dataset.
2) Create an ephemeral episode temp directory and write task metadata.
3) Run a tool-using worker (LLM + bash function tool) in that directory.
4) Evaluate rollout answers submitted through `submit_solution` against ground
   truth with reward util.
5) Append run metadata to a growing JSONL log.
6) Print a one-line summary.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.budget_ledger import (
    append_budget_event,
    budget_ledger_transaction,
    new_instance_uuid,
    read_budget_status,
)
from utils.codex_runner import resolve_codex_runner_bin, run_codex_rollout
from utils.hf_datasets import HFDatasetDataLoader
from utils.openrouter import (
    OpenRouterAPIError,
    bash_tool,
    budget_status_tool,
    call_openrouter_with_tools,
    get_tool_calls,
    spawn_child_tool,
    submit_solution_tool,
    transfer_tokens_tool,
)
from utils.reward import compute_rollout_reward
from utils.task_store import (
    compute_problem_uid,
    write_private_problem_record,
)


@dataclass
class Task:
    task_id: str
    question: str
    answer: str
    raw: dict[str, Any]


@dataclass
class RolloutResult:
    rollout_index: int
    record: dict[str, Any]
    successful_dir: Path | None
    summary: str
    error: str | None = None


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
DEFAULT_ROLLOUT_TOKEN_BUDGET_TOKENS = 300_000
DEFAULT_SOLVE_REWARD_TOKEN_CREDIT_TOKENS = 300_000
DEFAULT_RUNTIME_ROOT = Path.home() / "Documents" / "metalanguage_runs"
DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
BUNDLED_BOOTSTRAP_SEED_DIR = PROJECT_ROOT / "seeds" / "bootstrap"
CODEX_READ_README_BASE_INSTRUCTIONS = "Read README.md."


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


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _task_from_row(
    *,
    row: dict[str, Any],
    question_key: str | None,
    answer_key: str | None,
    id_key: str | None,
) -> Task:
    q = _first_present(row, [question_key] if question_key else [])
    if q is None:
        q = _first_present(row, ["question", "problem", "prompt", "input"])

    a = _first_present(row, [answer_key] if answer_key else [])
    if a is None:
        a = _first_present(row, ["answer", "solution", "ground_truth", "target"])

    tid = _first_present(row, [id_key] if id_key else [])
    if tid is None:
        tid = _first_present(row, ["id", "task_id", "problem_id", "uuid", "index"])

    if q is None or a is None:
        keys = ", ".join(sorted(row.keys()))
        raise ValueError(
            "Could not infer question/answer fields from dataset row. "
            f"Available keys: {keys}. Pass --question-key/--answer-key explicitly."
        )

    if tid is None:
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:12]
        tid = f"row_{digest}"

    return Task(task_id=str(tid), question=str(q), answer=str(a), raw=row)


def sample_task(
    *,
    dataset_name: str,
    split: str,
    config_name: str | None,
    seed: int,
    question_key: str | None,
    answer_key: str | None,
    id_key: str | None,
    dataset_cache_dir: Path | None = None,
) -> Task:
    load_kwargs: dict[str, Any] = {}
    if dataset_cache_dir is not None:
        load_kwargs["cache_dir"] = str(dataset_cache_dir)

    loader = HFDatasetDataLoader(
        dataset_name=dataset_name,
        split=split,
        config_name=config_name,
        batch_size=1,
        shuffle=True,
        seed=seed,
        **load_kwargs,
    )

    batch = next(iter(loader))
    row = batch[0]

    return _task_from_row(
        row=row,
        question_key=question_key,
        answer_key=answer_key,
        id_key=id_key,
    )


def iter_tasks(
    *,
    dataset_name: str,
    split: str,
    config_name: str | None,
    seed: int,
    question_key: str | None,
    answer_key: str | None,
    id_key: str | None,
    start_task_index: int = 0,
    max_tasks: int | None = None,
    dataset_cache_dir: Path | None = None,
):
    load_kwargs: dict[str, Any] = {}
    if dataset_cache_dir is not None:
        load_kwargs["cache_dir"] = str(dataset_cache_dir)

    loader = HFDatasetDataLoader(
        dataset_name=dataset_name,
        split=split,
        config_name=config_name,
        batch_size=1,
        shuffle=True,
        seed=seed,
        **load_kwargs,
    )

    yielded = 0
    for index, batch in enumerate(loader):
        if index < start_task_index:
            continue
        if max_tasks is not None and yielded >= max_tasks:
            break
        row = batch[0]
        yielded += 1
        yield index, _task_from_row(
            row=row,
            question_key=question_key,
            answer_key=answer_key,
            id_key=id_key,
        )


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


def _format_task_markdown(*, task: Task) -> str:
    lines = [
        "# Task",
        "",
        "## Question",
        "",
        task.question.strip(),
    ]

    options = _first_present(task.raw, ["options", "choices", "answer_choices", "candidates"])
    if isinstance(options, list) and options:
        lines.extend(["", "## Options", ""])
        for idx, option in enumerate(options):
            label = chr(65 + idx) if idx < 26 else str(idx)
            lines.append(f"{label}. {option}")
    elif isinstance(options, dict) and options:
        lines.extend(["", "## Options", ""])
        for key, option in options.items():
            lines.append(f"- {key}: {option}")

    lines.append("")
    return "\n".join(lines)


def _format_runtime_markdown(
    *,
    instance_uuid: str,
    rollout_token_budget_tokens: int | None,
    live_peer_instances: list[dict[str, Any]] | None = None,
    parent_instance_uuid: str | None = None,
) -> str:
    lines = [
        "# Runtime",
        "",
        "## Paths",
        "",
        "- task: task.md",
        "- seed_output: seed_output/",
        "- archive: archive/",
        "- shared_workspace: shared_workspace/",
        "",
        "## Runtime Values",
        "",
        f"- instance_uuid: {instance_uuid}",
        f"- parent_instance_uuid: {parent_instance_uuid or ''}",
        f"- rollout_token_budget_tokens: {rollout_token_budget_tokens if rollout_token_budget_tokens is not None else ''}",
    ]
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


def _parse_transfer_tokens_arguments(args: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    target_instance_uuid = args.get("target_instance_uuid", args.get("targetInstanceUuid"))
    if not isinstance(target_instance_uuid, str) or not target_instance_uuid.strip():
        return None, None, "transfer_tokens requires a non-empty string target_instance_uuid"

    raw_amount = args.get("amount_tokens", args.get("amountTokens"))
    try:
        amount_tokens = int(raw_amount)
    except (TypeError, ValueError):
        return None, None, "transfer_tokens requires integer amount_tokens"
    if amount_tokens <= 0:
        return None, None, "amount_tokens must be > 0"

    return target_instance_uuid.strip(), amount_tokens, None


def _parse_spawn_child_arguments(args: dict[str, Any]) -> tuple[str | None, int | None, str | None]:
    seed_dir = args.get("seed_dir", args.get("seedDir", args.get("seed")))
    if not isinstance(seed_dir, str) or not seed_dir.strip():
        return None, None, "spawn_child requires a non-empty string seed_dir"

    raw_budget = args.get("initial_budget_tokens", args.get("initialBudgetTokens"))
    try:
        initial_budget_tokens = int(raw_budget)
    except (TypeError, ValueError):
        return None, None, "spawn_child requires integer initial_budget_tokens"
    if initial_budget_tokens <= 0:
        return None, None, "initial_budget_tokens must be > 0"

    return seed_dir, initial_budget_tokens, None


def _parse_submit_solution_arguments(args: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    answer = args.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None, None, None, "submit_solution requires a non-empty string answer"

    raw_task_id = args.get("task_id", args.get("taskId"))
    reported_task_id = str(raw_task_id) if raw_task_id is not None else None
    raw_problem_uid = args.get("problem_uid", args.get("problemUid"))
    reported_problem_uid = str(raw_problem_uid) if raw_problem_uid is not None else None
    return answer.strip(), reported_task_id, reported_problem_uid, None


def _iter_budget_events(events_path: Path) -> list[dict[str, Any]]:
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _solve_reward_credit_total(events_path: Path, instance_uuid: str) -> int:
    total = 0
    for event in _iter_budget_events(events_path):
        if event.get("event_type") != "solve_reward_credit":
            continue
        if event.get("instance_uuid") != instance_uuid:
            continue
        try:
            total += int(event.get("amount_tokens") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _latest_solution_scored_event(events_path: Path, instance_uuid: str) -> dict[str, Any] | None:
    latest = None
    for event in _iter_budget_events(events_path):
        if event.get("event_type") == "solution_scored" and event.get("instance_uuid") == instance_uuid:
            latest = event
    return latest


def _resolve_spawn_seed_dir(context: dict[str, Any], seed_dir: str) -> tuple[Path | None, str | None]:
    workdir = Path(str(context["workdir"])).resolve()
    raw_path = Path(seed_dir).expanduser()
    candidate = raw_path.resolve() if raw_path.is_absolute() else (workdir / raw_path).resolve()
    if candidate == workdir or not _is_within(candidate, workdir):
        return None, "seed_dir must be a workspace-local directory, not the rollout workspace root"
    if not candidate.is_dir():
        return None, f"seed_dir is not a directory: {seed_dir}"
    readme = candidate / "README.md"
    if not readme.is_file() or not readme.read_text(encoding="utf-8").strip():
        return None, "seed_dir must contain a non-empty README.md"
    return candidate, None


def _write_continuation_context(context: dict[str, Any], control_dir: Path) -> Path:
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
    budget_ledger_events: Path,
    spawn_slots_path: Path,
    spawn_slots_dir: Path,
    live_peer_instances: list[dict[str, Any]],
    progress_log_path: Path,
    generation: int,
    seed: int,
    task_index: int,
    task_id: str,
    rollout_index: int,
    rollout_username: str,
    instance_uuid: str,
    problem_uid: str,
    private_problem_path: Path,
    task_markdown: str,
    rollout_token_budget_tokens: int | None,
    solve_reward_token_credit_tokens: int,
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
        "budget_ledger_events": str(budget_ledger_events),
        "spawn_slots_path": str(spawn_slots_path),
        "spawn_slots_dir": str(spawn_slots_dir),
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
        "problem_uid": problem_uid,
        "private_problem_path": str(private_problem_path),
        "task_markdown": task_markdown,
        "rollout_token_budget_tokens": rollout_token_budget_tokens,
        "solve_reward_token_credit_tokens": solve_reward_token_credit_tokens,
        "worker_timeout_seconds": worker_timeout_seconds,
        "bash_timeout_seconds": bash_timeout_seconds,
        "openrouter_max_retries": openrouter_max_retries,
        "codex_runner_bin": str(codex_runner_bin) if codex_runner_bin is not None else None,
        "codex_home": str(codex_home),
        "codex_sandbox_mode": codex_sandbox_mode,
        "codex_initial_prompt": codex_initial_prompt,
        "codex_base_instructions": codex_base_instructions,
    }


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


def _submit_solution(
    *,
    context: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    answer, reported_task_id, reported_problem_uid, error = _parse_submit_solution_arguments(args)
    if error is not None or answer is None:
        return {
            "success": False,
            "error": error or "invalid submit_solution arguments",
        }

    instance_uuid = str(context["instance_uuid"])
    budget_ledger_events = Path(str(context["budget_ledger_events"]))
    problem_uid = str(context["problem_uid"])
    task_id = str(context["task_id"])
    private_problem_path = Path(str(context["private_problem_path"]))
    reward = compute_rollout_reward(
        submitted_answer=answer,
        expected_task_id=task_id,
        expected_problem_uid=problem_uid,
        reported_task_id=reported_task_id,
        reported_problem_uid=reported_problem_uid,
        private_problem_path=private_problem_path,
    )
    solved = bool(reward >= 1.0)
    try:
        configured_credit_tokens = int(context.get("solve_reward_token_credit_tokens") or 0)
    except (TypeError, ValueError):
        configured_credit_tokens = 0
    prior_credit_tokens = _solve_reward_credit_total(budget_ledger_events, instance_uuid)
    credited_tokens = configured_credit_tokens if solved and prior_credit_tokens <= 0 else 0

    metadata = {
        "generation": context["generation"],
        "seed": context["seed"],
        "task_index": context["task_index"],
        "rollout_index": context["rollout_index"],
        "rollout_username": context["rollout_username"],
        "task_id": task_id,
        "problem_uid": problem_uid,
        "reported_problem_uid": reported_problem_uid,
        "reported_task_id": reported_task_id,
        "submitted_answer": answer,
        "solved": solved,
        "reward": reward,
        "solve_reward_credit_tokens": credited_tokens,
        "submission_source": "submit_solution",
    }
    append_budget_event(
        budget_ledger_events,
        event_type="solution_scored",
        instance_uuid=instance_uuid,
        metadata=metadata,
    )
    if credited_tokens > 0:
        append_budget_event(
            budget_ledger_events,
            event_type="solve_reward_credit",
            instance_uuid=instance_uuid,
            amount_tokens=credited_tokens,
            metadata={
                "generation": context["generation"],
                "seed": context["seed"],
                "task_index": context["task_index"],
                "rollout_index": context["rollout_index"],
                "rollout_username": context["rollout_username"],
                "task_id": task_id,
                "problem_uid": problem_uid,
                "reward": reward,
            },
        )
    total_credited_tokens = prior_credit_tokens + credited_tokens
    budget_status = read_budget_status(budget_ledger_events, instance_uuid)
    return {
        "success": True,
        "correct": solved,
        "solved": solved,
        "reward": reward,
        "credited_tokens": credited_tokens,
        "total_credited_tokens": total_credited_tokens,
        "reported_problem_uid": reported_problem_uid,
        "reported_task_id": reported_task_id,
        "budget_status": budget_status,
    }


def _transfer_tokens(
    *,
    context: dict[str, Any],
    args: dict[str, Any],
    source_budget: dict[str, Any],
) -> dict[str, Any]:
    target_instance_uuid, amount_tokens, error = _parse_transfer_tokens_arguments(args)
    if error is not None or target_instance_uuid is None or amount_tokens is None:
        return {
            "success": False,
            "transfer_committed": False,
            "error": error or "invalid transfer_tokens arguments",
        }

    source_instance_uuid = str(context["instance_uuid"])
    if target_instance_uuid == source_instance_uuid:
        return {
            "success": False,
            "transfer_committed": False,
            "error": "transfer_tokens target_instance_uuid must be a different live peer",
        }

    peers = context.get("live_peer_instances")
    if not isinstance(peers, list):
        peers = []
    target_peer = next(
        (
            peer
            for peer in peers
            if isinstance(peer, dict) and peer.get("instance_uuid") == target_instance_uuid
        ),
        None,
    )
    if target_peer is None:
        return {
            "success": False,
            "transfer_committed": False,
            "error": "target_instance_uuid is not a live peer for this task",
            "target_instance_uuid": target_instance_uuid,
        }

    transfer_event = {
        "source_instance_uuid": source_instance_uuid,
        "target_instance_uuid": target_instance_uuid,
        "amount_tokens": amount_tokens,
        "source_task_index": context["task_index"],
        "source_task_id": context["task_id"],
        "source_rollout_index": context["rollout_index"],
        "source_rollout_username": context["rollout_username"],
        "target_rollout_index": target_peer.get("rollout_index"),
        "target_rollout_username": target_peer.get("rollout_username"),
        "source_budget": source_budget,
    }

    try:
        budget_ledger_events = Path(str(context["budget_ledger_events"]))
        transaction = budget_ledger_transaction(
            budget_ledger_events,
            debit_instance_uuid=source_instance_uuid,
            required_tokens=amount_tokens,
            debit_status_floor=source_budget,
            build_event_specs=lambda budget_status: [
                {
                    "event_type": "budget_transferred",
                    "instance_uuid": source_instance_uuid,
                    "amount_tokens": amount_tokens,
                    "metadata": {
                        **transfer_event,
                        "source_budget": budget_status,
                    },
                }
            ],
        )
        if not transaction.get("success"):
            return {
                "success": False,
                "transfer_committed": False,
                "target_instance_uuid": target_instance_uuid,
                "amount_tokens": amount_tokens,
                "error": transaction.get("error") or "transfer_tokens failed",
                "budget_status": transaction.get("budget_status"),
            }
        event = transaction["events"][0]
        return {
            "success": True,
            "transfer_committed": True,
            "transfer_id": event["event_id"],
            "target_instance_uuid": target_instance_uuid,
            "amount_tokens": amount_tokens,
            "budget_status_before": transaction.get("budget_status_before"),
            "budget_status_after": transaction.get("budget_status_after"),
        }
    except BaseException as exc:
        return {
            "success": False,
            "transfer_committed": False,
            "target_instance_uuid": target_instance_uuid,
            "amount_tokens": amount_tokens,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _claim_spawn_slot(
    *,
    context: dict[str, Any],
    child_instance_uuid: str,
    source_seed_dir: Path,
    initial_budget_tokens: int,
    parent_budget: dict[str, Any],
) -> dict[str, Any]:
    slots_path = Path(str(context["spawn_slots_path"]))
    slots_dir = Path(str(context["spawn_slots_dir"]))
    lock_path = slots_path.with_suffix(slots_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    slots_dir.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        state = _read_json_file(slots_path, {})
        slots = state.get("slots") if isinstance(state, dict) else None
        if not isinstance(slots, list):
            slots = []

        slot_index = len(slots)
        child_seed_dir = slots_dir / f"slot_{slot_index:03d}_{child_instance_uuid[:8]}"
        child_seed_dir.mkdir(parents=True, exist_ok=False)
        copy_seed_workspace(source_seed_dir, child_seed_dir)
        metadata = {
            "child_instance_uuid": child_instance_uuid,
            "slot_index": slot_index,
            "parent_instance_uuid": context["instance_uuid"],
            "parent_rollout_username": context["rollout_username"],
            "initial_budget_tokens": initial_budget_tokens,
            "assigned_budget_tokens": initial_budget_tokens,
            "source_seed_dir": str(source_seed_dir),
            "source_task_index": context["task_index"],
            "source_task_id": context["task_id"],
            "source_rollout_index": context["rollout_index"],
            "parent_budget": parent_budget,
        }
        slot_record = {
            **metadata,
            "seed_dir": str(child_seed_dir),
        }
        slots.append(slot_record)
        _write_json_file_atomic(
            slots_path,
            {
                "source_task_index": context["task_index"],
                "source_task_id": context["task_id"],
                "slots": slots,
            },
        )
        return {
            "success": True,
            "slot_claimed": True,
            "reservation_committed": True,
            "slot_index": slot_index,
            "child_instance_uuid": child_instance_uuid,
            "child_seed_dir": str(child_seed_dir),
            "initial_budget_tokens": initial_budget_tokens,
            "assigned_budget_tokens": initial_budget_tokens,
            "claimed_slots": len(slots),
        }


def _load_spawned_child_seed_dirs(spawn_slots_path: Path) -> list[Path]:
    state = _read_json_file(spawn_slots_path, {})
    slots = state.get("slots") if isinstance(state, dict) else None
    if not isinstance(slots, list):
        return []
    seed_dirs: list[Path] = []
    for slot in sorted(slots, key=lambda item: int(item.get("slot_index", 0)) if isinstance(item, dict) else 0):
        if not isinstance(slot, dict):
            continue
        seed_dir = slot.get("seed_dir")
        if isinstance(seed_dir, str) and seed_dir:
            seed_dirs.append(Path(seed_dir))
    return seed_dirs


def _spawn_slots_path_for_child_seed_dir(seed_dir: Path) -> Path | None:
    slots_dir = seed_dir.parent
    suffix = "_next_iteration"
    if not slots_dir.name.endswith(suffix):
        return None
    return slots_dir.with_name(f"{slots_dir.name.removesuffix(suffix)}_spawn_slots.json")


def _spawn_slot_seed_dir_matches(slot: dict[str, Any], seed_dir: Path) -> bool:
    raw_seed_dir = slot.get("seed_dir")
    if not isinstance(raw_seed_dir, str) or not raw_seed_dir:
        return False
    try:
        return Path(raw_seed_dir).resolve() == seed_dir.resolve()
    except OSError:
        return raw_seed_dir == str(seed_dir)


def _spawn_child_metadata_for_seed_dir(seed_dir: Path) -> dict[str, Any]:
    slots_path = _spawn_slots_path_for_child_seed_dir(seed_dir)
    if slots_path is not None:
        state = _read_json_file(slots_path, {})
        slots = state.get("slots") if isinstance(state, dict) else None
        if isinstance(slots, list):
            for slot in slots:
                if isinstance(slot, dict) and _spawn_slot_seed_dir_matches(slot, seed_dir):
                    return slot
    return {}


def _seed_budget_tokens(seed_dir: Path) -> int | None:
    metadata = _spawn_child_metadata_for_seed_dir(seed_dir)
    try:
        budget = int(metadata.get("initial_budget_tokens"))
    except (TypeError, ValueError):
        return None
    return budget if budget > 0 else None


def _seed_child_instance_uuid(seed_dir: Path) -> str | None:
    metadata = _spawn_child_metadata_for_seed_dir(seed_dir)
    child_instance_uuid = metadata.get("child_instance_uuid")
    if isinstance(child_instance_uuid, str) and child_instance_uuid:
        return child_instance_uuid
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _resolve_runtime_root(value: str) -> Path:
    documents_dir = (Path.home() / "Documents").resolve()
    raw_root = Path(value).expanduser()
    root = raw_root.resolve() if raw_root.is_absolute() else (documents_dir / raw_root).resolve()
    if not _is_within(root, documents_dir):
        raise ValueError(f"--runtime-root must stay inside {documents_dir}: {root}")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_runtime_path(value: str, runtime_root: Path, label: str) -> Path:
    raw_path = Path(value).expanduser()
    path = raw_path.resolve() if raw_path.is_absolute() else (runtime_root / raw_path).resolve()
    if not _is_within(path, runtime_root):
        raise ValueError(f"{label} must stay inside --runtime-root {runtime_root}: {path}")
    return path


def _configure_runtime_environment(runtime_root: Path) -> Path:
    cache_root = runtime_root / "cache"
    dataset_cache_dir = cache_root / "huggingface_datasets"
    env_dirs = {
        "XDG_CACHE_HOME": cache_root / "xdg",
        "HF_HOME": cache_root / "huggingface",
        "HF_DATASETS_CACHE": dataset_cache_dir,
        "TMPDIR": runtime_root / "tmp" / "process",
    }
    for name, path in env_dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    return dataset_cache_dir


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


def copy_seed_workspace(parent_dir: Path, workdir: Path) -> None:
    """Copy a seed workspace directory into a rollout workspace."""
    if not parent_dir.exists():
        return

    def _ignore_symlinks(directory: str, names: list[str]) -> list[str]:
        return [name for name in names if (Path(directory) / name).is_symlink()]

    for item in parent_dir.iterdir():
        if item.is_symlink():
            continue
        dest = workdir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True, ignore=_ignore_symlinks)
        elif item.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


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


def _extract_token_usage(response_json: dict[str, Any]) -> dict[str, int] | None:
    usage = response_json.get("usage")
    response = response_json.get("response")
    if not isinstance(usage, dict) and isinstance(response, dict):
        usage = response.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    if total_tokens <= 0:
        return None
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}


def _spawn_child_continuation(
    *,
    context: dict[str, Any],
    args: dict[str, Any],
    parent_budget: dict[str, Any],
    progress_callback: Any = None,
) -> dict[str, Any]:
    seed_dir_arg, initial_budget_tokens, error = _parse_spawn_child_arguments(args)
    if error is not None or seed_dir_arg is None or initial_budget_tokens is None:
        return {
            "success": False,
            "reservation_committed": False,
            "error": error or "invalid spawn_child arguments",
        }
    source_seed_dir, error = _resolve_spawn_seed_dir(context, seed_dir_arg)
    if error is not None or source_seed_dir is None:
        return {
            "success": False,
            "reservation_committed": False,
            "error": error or "invalid seed_dir",
        }

    budget_ledger_events = Path(str(context["budget_ledger_events"]))
    parent_instance_uuid = str(context["instance_uuid"])
    task_id = str(context["task_id"])
    problem_uid = str(context["problem_uid"])
    child_instance_uuid = new_instance_uuid()
    reservation_committed = False
    slot_index: int | None = None
    child_seed_dir: str | None = None
    slot_result: dict[str, Any] | None = None

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
                "rollout_index": int(context["rollout_index"]),
                "rollout_username": str(context["rollout_username"]),
                "task_id": task_id,
                "problem_uid": problem_uid,
                **payload,
            },
        )

    try:
        def _build_spawn_event_specs(budget_status: dict[str, Any]) -> list[dict[str, Any]]:
            nonlocal slot_result, slot_index, child_seed_dir
            slot_result = _claim_spawn_slot(
                context=context,
                child_instance_uuid=child_instance_uuid,
                source_seed_dir=source_seed_dir,
                initial_budget_tokens=initial_budget_tokens,
                parent_budget=budget_status,
            )
            if not slot_result.get("slot_claimed"):
                raise RuntimeError(slot_result.get("error") or "spawn_child slot was not claimed")
            slot_index = int(slot_result["slot_index"])
            child_seed_dir = str(slot_result["child_seed_dir"])
            return [
                {
                    "event_type": "child_spawned",
                    "instance_uuid": parent_instance_uuid,
                    "amount_tokens": initial_budget_tokens,
                    "metadata": {
                        "child_instance_uuid": child_instance_uuid,
                        "slot_index": slot_index,
                        "child_seed_dir": child_seed_dir,
                        "parent_tokens_spent": budget_status.get("tokens_spent"),
                        "parent_reserved_for_children_before": budget_status.get(
                            "tokens_reserved_for_children"
                        ),
                        "initial_budget_tokens": initial_budget_tokens,
                        "assigned_budget_tokens": initial_budget_tokens,
                        "generation": int(context["generation"]),
                        "seed": int(context["seed"]),
                        "task_index": int(context["task_index"]),
                        "rollout_index": int(context["rollout_index"]),
                        "rollout_username": f"{context['rollout_username']}_slot_{slot_index:03d}",
                        "task_id": task_id,
                        "problem_uid": problem_uid,
                    },
                }
            ]

        transaction = budget_ledger_transaction(
            budget_ledger_events,
            debit_instance_uuid=parent_instance_uuid,
            required_tokens=initial_budget_tokens,
            debit_status_floor=parent_budget,
            build_event_specs=_build_spawn_event_specs,
        )
        if not transaction.get("success"):
            return {
                "success": False,
                "reservation_committed": False,
                "error": transaction.get("error") or "spawn_child failed",
                "requested_initial_budget_tokens": initial_budget_tokens,
                "budget_status": transaction.get("budget_status"),
            }
        if slot_result is None:
            raise RuntimeError("spawn_child transaction did not claim a slot")
        slot_index = int(slot_result["slot_index"])
        child_seed_dir = str(slot_result["child_seed_dir"])
        reservation_committed = True
        result = {
            **slot_result,
            "success": True,
            "reservation_committed": reservation_committed,
            "budget_status_before": transaction.get("budget_status_before"),
            "budget_status_after": transaction.get("budget_status_after"),
        }
        _progress("slot_claimed", **result)
        return result
    except BaseException as exc:
        result = {
            "success": False,
            "reservation_committed": reservation_committed,
            "child_instance_uuid": child_instance_uuid,
            "slot_index": slot_index,
            "child_seed_dir": child_seed_dir,
            "initial_budget_tokens": initial_budget_tokens,
            "error": f"{type(exc).__name__}: {exc}",
        }
        _progress("failed", **result)
        return result


def run_worker(
    *,
    api_key: str,
    model: str,
    workdir: Path,
    budget_ledger_events: Path,
    instance_uuid: str,
    rollout_token_budget_tokens: int | None,
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
    progress_callback: Any = None,
) -> WorkerResult:
    """Run a multi-turn tool-calling worker loop and return final assistant text."""
    conversation: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Read README.md.",
                }
            ],
        }
    ]

    final_text = ""
    command_index = 0
    turn_count = 0
    tokens_spent = 0
    spawned_child_slots: list[dict[str, Any]] = []
    started_at = time.monotonic()

    while True:
        turn_count += 1
        elapsed_seconds = time.monotonic() - started_at
        budget_status = read_budget_status(budget_ledger_events, instance_uuid)
        if rollout_token_budget_tokens is not None and int(budget_status["tokens_remaining"] or 0) <= 0:
            return WorkerResult(
                final_text=final_text,
                status="budget_exhausted",
                stop_reason="token_budget_exhausted",
                error_code="token_budget_exhausted",
                error_message=(
                    "Token budget exhausted: "
                    f"{int(budget_status['effective_rollout_token_budget_tokens'] or 0) - int(budget_status['tokens_remaining'] or 0)}/"
                    f"{budget_status['effective_rollout_token_budget_tokens']}."
                ),
                metadata={
                    "tokens_spent": budget_status["tokens_spent"],
                    "tokens_reserved_for_children": budget_status["tokens_reserved_for_children"],
                    "tokens_transferred_in": budget_status["tokens_transferred_in"],
                    "tokens_transferred_out": budget_status["tokens_transferred_out"],
                    "spawned_child_slots": spawned_child_slots,
                },
            )
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
                budget_status=budget_status,
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
                    submit_solution_tool,
                    budget_status_tool,
                    transfer_tokens_tool,
                    spawn_child_tool,
                ],
                tool_choice="auto",
                timeout=120,
                max_output_tokens=(
                    max(1, int(budget_status["tokens_remaining"] or 0))
                    if rollout_token_budget_tokens is not None
                    else None
                ),
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

        usage = _extract_token_usage(response)
        if usage is None and rollout_token_budget_tokens is not None:
            return WorkerResult(
                final_text=_extract_text_from_response(response) or final_text,
                status="budget_tracking_error",
                stop_reason="missing_token_usage",
                error_code="missing_token_usage",
                error_message="OpenRouter response did not include token usage for budget enforcement.",
            )
        if usage is not None:
            tokens_used = usage["total_tokens"]
            tokens_spent += tokens_used
            append_budget_event(
                budget_ledger_events,
                event_type="token_usage",
                instance_uuid=instance_uuid,
                amount_tokens=tokens_used,
                metadata={
                    "turn_count": turn_count,
                    "backend": "openrouter",
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "tokens_spent": tokens_spent,
                },
            )

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
        budget_status = read_budget_status(budget_ledger_events, instance_uuid)
        if progress_callback is not None:
            progress_callback(
                "worker_turn_completed",
                elapsed_seconds=round(time.monotonic() - started_at, 3),
                turn_count=turn_count,
                tool_call_count=len(tool_calls),
                response_status=response.get("status"),
                token_usage=usage,
                tokens_spent=budget_status["tokens_spent"],
                tokens_reserved_for_children=budget_status["tokens_reserved_for_children"],
                tokens_transferred_in=budget_status["tokens_transferred_in"],
                tokens_transferred_out=budget_status["tokens_transferred_out"],
                budget_status=budget_status,
                rollout_token_budget_tokens=rollout_token_budget_tokens,
            )
        if rollout_token_budget_tokens is not None and int(budget_status["tokens_remaining"] or 0) <= 0:
            return WorkerResult(
                final_text=_extract_text_from_response(response) or final_text,
                status="budget_exhausted",
                stop_reason="token_budget_exceeded",
                error_code="token_budget_exceeded",
                error_message=(
                    "Token budget exceeded: "
                    f"{int(budget_status['effective_rollout_token_budget_tokens'] or 0) - int(budget_status['tokens_remaining'] or 0)}/"
                    f"{budget_status['effective_rollout_token_budget_tokens']}."
                ),
                metadata={
                    "tokens_spent": budget_status["tokens_spent"],
                    "tokens_reserved_for_children": budget_status["tokens_reserved_for_children"],
                    "tokens_transferred_in": budget_status["tokens_transferred_in"],
                    "tokens_transferred_out": budget_status["tokens_transferred_out"],
                    "spawned_child_slots": spawned_child_slots,
                },
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
            if tool_name == "submit_solution":
                tool_result = _submit_solution(
                    context=continuation_context,
                    args=args,
                )
            elif tool_name == "budget_status":
                tool_result = read_budget_status(budget_ledger_events, instance_uuid)
            elif tool_name == "transfer_tokens":
                tool_result = _transfer_tokens(
                    context=continuation_context,
                    args=args,
                    source_budget=read_budget_status(budget_ledger_events, instance_uuid),
                )
            elif tool_name == "spawn_child":
                tool_result = _spawn_child_continuation(
                    context=continuation_context,
                    args=args,
                    parent_budget=read_budget_status(budget_ledger_events, instance_uuid),
                    progress_callback=progress_callback,
                )
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

    budget_status = read_budget_status(budget_ledger_events, instance_uuid)
    return WorkerResult(
        final_text=final_text,
        status="completed",
        stop_reason="final_message",
        metadata={
            "tokens_spent": budget_status["tokens_spent"],
            "tokens_reserved_for_children": budget_status["tokens_reserved_for_children"],
            "tokens_transferred_in": budget_status["tokens_transferred_in"],
            "tokens_transferred_out": budget_status["tokens_transferred_out"],
            "effective_rollout_token_budget_tokens": budget_status[
                "effective_rollout_token_budget_tokens"
            ],
            "spawned_child_slots": spawned_child_slots,
        },
    )


def run_codex_worker(
    *,
    runner_bin: Path,
    model: str,
    workdir: Path,
    control_dir: Path,
    worker_state_dir: Path,
    budget_ledger_events: Path,
    instance_uuid: str,
    rollout_token_budget_tokens: int | None,
    codex_home: Path,
    seed_output_dir: Path,
    archive_repo_dir: Path,
    shared_workspace_dir: Path,
    rollout_username: str,
    timeout_seconds: int,
    sandbox_mode: str,
    initial_user_text: str,
    base_instructions: str | None = None,
    continuation_context_path: Path | None = None,
    progress_callback: Any = None,
) -> WorkerResult:
    """Run one rollout through the Metalanguage-owned Codex runner."""

    def record_token_usage(usage: dict[str, int], tokens_spent: int) -> None:
        append_budget_event(
            budget_ledger_events,
            event_type="token_usage",
            instance_uuid=instance_uuid,
            amount_tokens=usage["total_tokens"],
            metadata={
                "backend": "codex",
                "input_tokens": usage["input_tokens"],
                "cached_input_tokens": usage["cached_input_tokens"],
                "output_tokens": usage["output_tokens"],
                "reasoning_output_tokens": usage["reasoning_output_tokens"],
                "tokens_spent": tokens_spent,
            },
        )

    result = run_codex_rollout(
        runner_bin=runner_bin,
        model=model,
        workdir=workdir,
        control_dir=control_dir,
        worker_state_dir=worker_state_dir,
        codex_home=codex_home,
        seed_output_dir=seed_output_dir,
        archive_repo_dir=archive_repo_dir,
        shared_workspace_dir=shared_workspace_dir,
        rollout_username=rollout_username,
        timeout_seconds=timeout_seconds,
        sandbox_mode=sandbox_mode,
        initial_user_text=initial_user_text,
        base_instructions=base_instructions,
        rollout_token_budget_tokens=rollout_token_budget_tokens,
        instance_uuid=instance_uuid,
        spawn_child_handler_context_path=continuation_context_path,
        token_usage_callback=record_token_usage,
        progress_callback=progress_callback,
    )
    metadata = {
        key: result.get(key)
        for key in [
            "thread_id",
            "session_id",
            "tokens_spent",
            "tokens_reserved_for_children",
            "tokens_transferred_in",
            "tokens_transferred_out",
            "rollout_token_budget_tokens",
            "effective_rollout_token_budget_tokens",
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


def resolve_codex_base_instructions(mode: str) -> str | None:
    """Return fixed Codex base instructions, or None for Codex defaults."""
    if mode == "codex":
        return None
    if mode == "read-readme":
        return CODEX_READ_README_BASE_INSTRUCTIONS
    raise ValueError(f"Unknown Codex base instructions mode: {mode}")


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


def load_parent_pool(parent_pool_path: Path) -> list[Path]:
    if not parent_pool_path.exists():
        return []
    try:
        raw = json.loads(parent_pool_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []

    paths: list[Path] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            continue
        p = Path(item)
        if p.exists():
            paths.append(p)
    return paths


def save_parent_pool(parent_pool_path: Path, parent_pool: list[Path]) -> None:
    parent_pool_path.parent.mkdir(parents=True, exist_ok=True)
    parent_pool_path.write_text(
        json.dumps([str(path) for path in parent_pool], ensure_ascii=False, indent=2),
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
            "# Local world repo\n\nPersistent local git substrate for rollout lineage.\n",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one RLVR episode.")
    parser.add_argument("--dataset-name", default="m-a-p/SuperGPQA")
    parser.add_argument("--split", default="train")
    parser.add_argument("--config-name", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--worker-backend",
        choices=["openrouter", "codex"],
        default="openrouter",
        help="Worker runtime to use for rollouts.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument(
        "--num-rollouts",
        type=int,
        default=DEFAULT_NUM_ROLLOUTS,
        help="Number of bootstrap rollouts to run before spawn_child controls lineage width.",
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
            "next-iteration child slots were produced."
        ),
    )
    parser.add_argument("--question-key", default=None)
    parser.add_argument("--answer-key", default=None)
    parser.add_argument("--id-key", default=None)
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
            "Seed workspace copied into bootstrap rollouts before any parent seed exists. "
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
        "--rollout-token-budget-tokens",
        type=int,
        default=DEFAULT_ROLLOUT_TOKEN_BUDGET_TOKENS,
        help=(
            "Per-rollout model token budget. No further model calls are made "
            "after reported usage exhausts it."
        ),
    )
    parser.add_argument(
        "--solve-reward-token-credit-tokens",
        type=int,
        default=DEFAULT_SOLVE_REWARD_TOKEN_CREDIT_TOKENS,
        help=(
            "Token budget credited to a rollout when submit_solution scores "
            "a correct answer. Set to 0 to disable solve reward credits."
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
        default="Read README.md.",
        help="Initial user text submitted to the Codex runner for each rollout.",
    )
    parser.add_argument(
        "--codex-base-instructions-mode",
        choices=["codex", "read-readme"],
        default="read-readme",
        help=(
            "Codex base-instructions mode. 'codex' uses the model catalog default; "
            "'read-readme' uses the fixed scaffold instruction `Read README.md.`."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.num_rollouts <= 0:
        raise ValueError("--num-rollouts must be > 0")
    if args.worker_timeout_seconds <= 0:
        raise ValueError("--worker-timeout-seconds must be > 0")
    if args.bash_timeout_seconds <= 0:
        raise ValueError("--bash-timeout-seconds must be > 0")
    if args.openrouter_max_retries < 0:
        raise ValueError("--openrouter-max-retries must be >= 0")
    if args.rollout_token_budget_tokens is not None and args.rollout_token_budget_tokens <= 0:
        raise ValueError("--rollout-token-budget-tokens must be > 0 when set")
    if args.solve_reward_token_credit_tokens < 0:
        raise ValueError("--solve-reward-token-credit-tokens must be >= 0")

    load_dotenv()
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

    runtime_root = _resolve_runtime_root(args.runtime_root)
    runs_log_path = _resolve_runtime_path(args.runs_log, runtime_root, "--runs-log")
    progress_log_path = _resolve_runtime_path(args.progress_log, runtime_root, "--progress-log")
    outputs_dir = _resolve_runtime_path(args.outputs_dir, runtime_root, "--outputs-dir")
    fixed_temp_dir = _resolve_runtime_path(args.fixed_temp_dir, runtime_root, "--fixed-temp-dir")
    rollout_root = _resolve_runtime_path(args.rollout_temp_root, runtime_root, "--rollout-temp-root")
    task_store_dir = _resolve_runtime_path(args.task_store_dir, runtime_root, "--task-store-dir")
    archive_repo_dir = _resolve_runtime_path(args.archive_repo_dir, runtime_root, "--archive-repo-dir")
    bootstrap_seed_dir = _resolve_runtime_path(args.bootstrap_seed_dir, runtime_root, "--bootstrap-seed-dir")
    budget_ledger_events = runtime_root / "logs" / "budget_ledger.jsonl"
    dataset_cache_dir = _configure_runtime_environment(runtime_root)
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

    parent_pool: list[Path] = []

    existing_records: list[dict[str, Any]] = []
    if not args.no_resume:
        all_records = load_existing_run_records(runs_log_path)
        expected_codex_base_mode = (
            args.codex_base_instructions_mode if args.worker_backend == "codex" else None
        )
        existing_records = [
            rec
            for rec in all_records
            if rec.get("dataset_name") == args.dataset_name
            and rec.get("split") == args.split
            and rec.get("model") == args.model
            and rec.get("seed") == args.seed
            and rec.get("generation") == args.generation
            and rec.get("bootstrap_rollout_count", rec.get("num_rollouts")) == args.num_rollouts
            and rec.get("config_name") == args.config_name
            and rec.get("worker_backend", "openrouter") == args.worker_backend
            and rec.get(
                "configured_rollout_token_budget_tokens",
                rec.get("rollout_token_budget_tokens"),
            )
            == args.rollout_token_budget_tokens
            and rec.get(
                "configured_solve_reward_token_credit_tokens",
                rec.get("solve_reward_token_credit_tokens"),
            )
            == args.solve_reward_token_credit_tokens
            and (
                args.worker_backend != "codex"
                or rec.get("codex_base_instructions_mode", "codex") == expected_codex_base_mode
            )
        ]

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

    if not args.no_resume:
        parent_pool = load_parent_pool(parent_pool_path)

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

    if args.step:
        task_start_index = _next_step_task_index()
        task_limit = 1
        tasks = iter_tasks(
            dataset_name=args.dataset_name,
            split=args.split,
            config_name=args.config_name,
            seed=args.seed,
            question_key=args.question_key,
            answer_key=args.answer_key,
            id_key=args.id_key,
            start_task_index=task_start_index,
            max_tasks=task_limit,
            dataset_cache_dir=dataset_cache_dir,
        )
    elif args.all_tasks:
        tasks = iter_tasks(
            dataset_name=args.dataset_name,
            split=args.split,
            config_name=args.config_name,
            seed=args.seed,
            question_key=args.question_key,
            answer_key=args.answer_key,
            id_key=args.id_key,
            start_task_index=args.start_task_index,
            max_tasks=args.max_tasks,
            dataset_cache_dir=dataset_cache_dir,
        )
    else:
        tasks = [
            (
                0,
                sample_task(
                    dataset_name=args.dataset_name,
                    split=args.split,
                    config_name=args.config_name,
                    seed=args.seed,
                    question_key=args.question_key,
                    answer_key=args.answer_key,
                    id_key=args.id_key,
                    dataset_cache_dir=dataset_cache_dir,
                ),
            )
        ]

    for task_index, task in tasks:
        existing_task_records = existing_by_task.get(task_index, {})
        recorded_task_rollout_count = _recorded_task_rollout_count(existing_task_records)
        bootstrap_without_parent = task_index == 0 and not parent_pool
        task_rollout_count = (
            recorded_task_rollout_count
            if recorded_task_rollout_count is not None
            else (args.num_rollouts if bootstrap_without_parent else len(parent_pool))
        )
        if task_rollout_count <= 0:
            raise RuntimeError(
                f"No spawned child slots available for task_index={task_index}; "
                "lineage cannot advance without spawn_child."
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
                    _seed_child_instance_uuid(parent_pool[rollout_index]) or new_instance_uuid()
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
        problem_uid = compute_problem_uid(
            dataset_name=args.dataset_name,
            split=args.split,
            config_name=args.config_name,
            task_id=task.task_id,
            question=task.question,
        )
        private_problem_path = write_private_problem_record(
            task_store_dir=task_store_dir,
            problem_uid=problem_uid,
            row=task.raw,
        )
        spawn_slots_path = rollout_root / (
            f"{task_index:06d}_{_sanitize_for_path(task.task_id)}_spawn_slots.json"
        )
        spawn_slots_dir = rollout_root / (
            f"{task_index:06d}_{_sanitize_for_path(task.task_id)}_next_iteration"
        )

        if len(existing_task_records) >= task_rollout_count:
            continue

        def _run_one_rollout(rollout_index: int) -> RolloutResult:
            existing = existing_task_records.get(rollout_index)
            if existing is not None:
                raise RuntimeError(f"rollout {rollout_index} already exists and should not have been submitted")

            rollout_username = _rollout_username(rollout_index)
            sampled_parent: Path | None = (
                parent_pool[rollout_index] if rollout_index < len(parent_pool) else None
            )
            rollout_budget_tokens = (
                _seed_budget_tokens(sampled_parent)
                if sampled_parent is not None
                else args.rollout_token_budget_tokens
            )
            if rollout_budget_tokens is None:
                rollout_budget_tokens = args.rollout_token_budget_tokens
            instance_uuid = task_instance_uuids[rollout_index]
            rollout_control_dir = runtime_root / "logs" / "rollout_control" / instance_uuid
            rollout_state_dir = runtime_root / "logs" / "rollout_state" / instance_uuid
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
                    "task_id": task.task_id,
                    "problem_uid": problem_uid,
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    **fields,
                }
                append_progress_log(progress_log_path, progress_log_lock, record)

            if sampled_parent is None and task_index > 0:
                raise RuntimeError(
                    "No spawned child slot available for non-bootstrap rollout; "
                    f"task_index={task_index} rollout_index={rollout_index}"
                )
            append_budget_event(
                budget_ledger_events,
                event_type="instance_created",
                instance_uuid=instance_uuid,
                metadata={
                    "generation": args.generation,
                    "seed": args.seed,
                    "task_index": task_index,
                    "rollout_index": rollout_index,
                    "rollout_username": rollout_username,
                    "task_id": task.task_id,
                    "problem_uid": problem_uid,
                    "rollout_token_budget_tokens": rollout_budget_tokens,
                },
            )
            _progress(
                "rollout_started",
                instance_uuid=instance_uuid,
                parent_rollout_dir=str(sampled_parent) if sampled_parent else None,
                bootstrap_seed_dir=str(bootstrap_seed_dir) if sampled_parent is None else None,
            )
            archive_worktree = create_archive_worktree(
                archive_repo_dir=archive_repo_dir,
                worktree_root=archive_worktree_root,
                branch=f"rollout/{task_index:06d}-{rollout_index:03d}-{_sanitize_for_path(task.task_id)}",
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
            if sampled_parent is not None:
                copy_seed_workspace(sampled_parent, temp_dir)
            else:
                if not bootstrap_seed_dir.exists():
                    raise RuntimeError(f"Bootstrap seed directory does not exist: {bootstrap_seed_dir}")
                copy_seed_workspace(bootstrap_seed_dir, temp_dir)

            seed_output_dir = temp_dir / "seed_output"
            seed_output_dir.mkdir(parents=True, exist_ok=True)
            archive_link = temp_dir / "archive"
            shared_workspace_link = temp_dir / "shared_workspace"
            _replace_with_symlink(archive_link, archive_worktree.path)
            _replace_with_symlink(shared_workspace_link, shared_workspace_dir)

            task_markdown = _format_task_markdown(task=task)
            task_file = temp_dir / "task.md"
            task_file.write_text(task_markdown, encoding="utf-8")
            runtime_file = temp_dir / "runtime.md"
            runtime_file.write_text(
                _format_runtime_markdown(
                    instance_uuid=instance_uuid,
                    rollout_token_budget_tokens=rollout_budget_tokens,
                    live_peer_instances=rollout_live_peer_instances,
                ),
                encoding="utf-8",
            )
            codex_base_instructions = (
                resolve_codex_base_instructions(args.codex_base_instructions_mode)
                if args.worker_backend == "codex"
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
                budget_ledger_events=budget_ledger_events,
                spawn_slots_path=spawn_slots_path,
                spawn_slots_dir=spawn_slots_dir,
                live_peer_instances=rollout_live_peer_instances,
                progress_log_path=progress_log_path,
                generation=args.generation,
                seed=args.seed,
                task_index=task_index,
                task_id=task.task_id,
                rollout_index=rollout_index,
                rollout_username=rollout_username,
                instance_uuid=instance_uuid,
                problem_uid=problem_uid,
                private_problem_path=private_problem_path,
                task_markdown=task_markdown,
                rollout_token_budget_tokens=rollout_budget_tokens,
                solve_reward_token_credit_tokens=args.solve_reward_token_credit_tokens,
                worker_timeout_seconds=args.worker_timeout_seconds,
                bash_timeout_seconds=args.bash_timeout_seconds,
                openrouter_max_retries=args.openrouter_max_retries,
                codex_runner_bin=codex_runner_bin,
                codex_home=codex_home,
                codex_sandbox_mode=args.codex_sandbox_mode,
                codex_initial_prompt=args.codex_initial_prompt,
                codex_base_instructions=codex_base_instructions,
            )
            continuation_context_path = (
                _write_continuation_context(continuation_context, rollout_control_dir)
                if args.worker_backend == "codex"
                else None
            )
            _progress(
                "workspace_prepared",
                working_directory=str(temp_dir),
                task_file=str(task_file),
                runtime_file=str(runtime_file),
                seed_output_dir=str(seed_output_dir),
                rollout_control_dir=str(rollout_control_dir) if args.worker_backend == "codex" else None,
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
                            budget_ledger_events=budget_ledger_events,
                            instance_uuid=instance_uuid,
                            rollout_token_budget_tokens=rollout_budget_tokens,
                            codex_home=codex_home,
                            seed_output_dir=seed_output_dir,
                            archive_repo_dir=archive_worktree.path,
                            shared_workspace_dir=shared_workspace_dir,
                            rollout_username=rollout_username,
                            timeout_seconds=args.worker_timeout_seconds,
                            sandbox_mode=args.codex_sandbox_mode,
                            initial_user_text=args.codex_initial_prompt,
                            base_instructions=codex_base_instructions,
                            continuation_context_path=continuation_context_path,
                            progress_callback=_progress,
                        )
                    else:
                        if api_key is None:
                            raise RuntimeError("OPENROUTER_API_KEY is required for the OpenRouter backend.")
                        worker_result = run_worker(
                            api_key=api_key,
                            model=args.model,
                            workdir=temp_dir,
                            budget_ledger_events=budget_ledger_events,
                            instance_uuid=instance_uuid,
                            rollout_token_budget_tokens=rollout_budget_tokens,
                            seed_output_dir=seed_output_dir,
                            archive_repo_dir=archive_worktree.path,
                            shared_workspace_dir=shared_workspace_dir,
                            worker_state_dir=rollout_state_dir,
                            shared_workspace_write_log=shared_workspace_write_log,
                            shared_workspace_lock=shared_workspace_lock,
                            task_index=task_index,
                            task_id=task.task_id,
                            rollout_index=rollout_index,
                            rollout_username=rollout_username,
                            timeout_seconds=args.worker_timeout_seconds,
                            bash_timeout_seconds=args.bash_timeout_seconds,
                            openrouter_max_retries=args.openrouter_max_retries,
                            continuation_context=continuation_context,
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
            latest_solution_event = _latest_solution_scored_event(
                budget_ledger_events,
                instance_uuid,
            )
            solution_feedback = None
            if latest_solution_event is not None:
                latest_metadata = latest_solution_event.get("metadata")
                latest_metadata = latest_metadata if isinstance(latest_metadata, dict) else {}
                reported_problem_uid = latest_metadata.get("reported_problem_uid")
                reported_task_id = latest_metadata.get("reported_task_id")
                reward = float(latest_metadata.get("reward") or 0.0)
                solved = bool(latest_metadata.get("solved"))
                solve_reward_credit_tokens = _solve_reward_credit_total(
                    budget_ledger_events,
                    instance_uuid,
                )
                solution_feedback = {
                    "correct": solved,
                    "solved": solved,
                    "reward": reward,
                    "credited_tokens": int(latest_metadata.get("solve_reward_credit_tokens") or 0),
                    "total_credited_tokens": solve_reward_credit_tokens,
                    "reported_problem_uid": reported_problem_uid,
                    "reported_task_id": reported_task_id,
                    "budget_status": read_budget_status(budget_ledger_events, instance_uuid),
                }
            else:
                reported_problem_uid = None
                reported_task_id = None
                reward = 0.0
                solved = False
                solve_reward_credit_tokens = 0
                _progress(
                    "solution_missing",
                    error="submit_solution was not called; no solution score or reward credit was recorded",
                )
            _progress(
                "rollout_scored",
                solved=solved,
                reward=reward,
                solve_reward_credit_tokens=solve_reward_credit_tokens,
                reported_problem_uid=reported_problem_uid,
                reported_task_id=reported_task_id,
            )

            output_dir = persist_episode_outputs(
                temp_dir,
                outputs_dir,
                f"{task.task_id}_rollout_{rollout_index:03d}",
            )
            _progress("episode_persisted", output_path=str(output_dir))

            seed_viable = False
            next_rollout_dir = None

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "generation": args.generation,
                "seed": args.seed,
                "task_index": task_index,
                "rollout_index": rollout_index,
                "rollout_username": rollout_username,
                "instance_uuid": instance_uuid,
                "task_id": task.task_id,
                "problem_uid": problem_uid,
                "reported_problem_uid": reported_problem_uid,
                "reported_task_id": reported_task_id,
                "parent_rollout_dir": str(sampled_parent) if sampled_parent else None,
                "bootstrap_seed_dir": str(bootstrap_seed_dir) if sampled_parent is None else None,
                "next_rollout_dir": str(next_rollout_dir) if next_rollout_dir is not None else None,
                "seed_viable": seed_viable,
                "budget_ledger_events": str(budget_ledger_events),
                "worker_status": worker_result.status,
                "worker_stop_reason": worker_result.stop_reason,
                "worker_error_code": worker_result.error_code,
                "worker_error_message": worker_result.error_message,
                "worker_backend": args.worker_backend,
                "worker_metadata": worker_result.metadata,
                "solved": solved,
                "reward": reward,
                "solve_reward_credit_tokens": solve_reward_credit_tokens,
                "solution_feedback": solution_feedback,
                "output_path": str(output_dir),
                "private_problem_path": str(private_problem_path),
                "shared_workspace_write_log": str(shared_workspace_write_log),
                "progress_log": str(progress_log_path),
                "dataset_name": args.dataset_name,
                "split": args.split,
                "model": args.model,
                "num_rollouts": args.num_rollouts,
                "bootstrap_rollout_count": args.num_rollouts,
                "task_rollout_count": task_rollout_count,
                "worker_timeout_seconds": args.worker_timeout_seconds,
                "bash_timeout_seconds": args.bash_timeout_seconds,
                "openrouter_max_retries": args.openrouter_max_retries,
                "configured_rollout_token_budget_tokens": args.rollout_token_budget_tokens,
                "rollout_token_budget_tokens": rollout_budget_tokens,
                "configured_solve_reward_token_credit_tokens": args.solve_reward_token_credit_tokens,
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
                "config_name": args.config_name,
                "runtime_root": str(runtime_root),
                "dataset_cache_dir": str(dataset_cache_dir),
                **archive_result,
            }

            summary = (
                f"gen={args.generation} seed={args.seed} task_index={task_index} rollout_index={rollout_index} "
                f"rollout_username={rollout_username} task_id={task.task_id} solved={solved} output={output_dir}"
            )
            if worker_result.status == "error":
                summary += f" error={worker_result.stop_reason}"
            return RolloutResult(
                rollout_index=rollout_index,
                record=record,
                successful_dir=next_rollout_dir,
                summary=summary,
                error=worker_result.error_message if worker_result.status == "error" else None,
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
                for future in as_completed(futures):
                    rollout_index = futures[future]
                    try:
                        results.append(future.result())
                    except BaseException as exc:
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
                                "task_id": task.task_id,
                                "problem_uid": problem_uid,
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
                                    "generation": args.generation,
                                    "seed": args.seed,
                                    "task_index": task_index,
                                    "rollout_index": rollout_index,
                                    "rollout_username": _rollout_username(rollout_index),
                                    "task_id": task.task_id,
                                    "problem_uid": problem_uid,
                                    "reported_problem_uid": None,
                                    "reported_task_id": None,
                                    "parent_rollout_dir": None,
                                    "bootstrap_seed_dir": str(bootstrap_seed_dir),
                                    "next_rollout_dir": None,
                                    "seed_viable": False,
                                    "worker_status": "error",
                                    "worker_stop_reason": type(exc).__name__,
                                    "worker_error_code": None,
                                    "worker_error_message": str(exc),
                                    "worker_backend": args.worker_backend,
                                    "worker_metadata": None,
                                    "solved": False,
                                    "reward": 0.0,
                                    "output_path": None,
                                    "private_problem_path": str(private_problem_path),
                                    "shared_workspace_write_log": str(shared_workspace_write_log),
                                    "progress_log": str(progress_log_path),
                                    "dataset_name": args.dataset_name,
                                    "split": args.split,
                                    "model": args.model,
                                    "num_rollouts": args.num_rollouts,
                                    "bootstrap_rollout_count": args.num_rollouts,
                                    "task_rollout_count": task_rollout_count,
                                    "worker_timeout_seconds": args.worker_timeout_seconds,
                                    "bash_timeout_seconds": args.bash_timeout_seconds,
                                    "openrouter_max_retries": args.openrouter_max_retries,
                                    "rollout_token_budget_tokens": args.rollout_token_budget_tokens,
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
                                    "config_name": args.config_name,
                                    "runtime_root": str(runtime_root),
                                    "dataset_cache_dir": str(dataset_cache_dir),
                                },
                                successful_dir=None,
                                summary=(
                                    f"gen={args.generation} seed={args.seed} task_index={task_index} "
                                    f"rollout_index={rollout_index} rollout_username={_rollout_username(rollout_index)} "
                                    f"task_id={task.task_id} solved=False output=None error={type(exc).__name__}"
                                ),
                                error=str(exc),
                            )
                        )

        _cleanup_rollout_shared_writes(shared_workspace_dir, shared_snapshot)

        for result in sorted(results, key=lambda item: item.rollout_index):
            append_run_log(runs_log_path, result.record)
            print(result.summary)

        spawned_child_dirs = _load_spawned_child_seed_dirs(spawn_slots_path)
        if spawned_child_dirs:
            parent_pool = spawned_child_dirs
            save_parent_pool(parent_pool_path, parent_pool)
        else:
            save_parent_pool(parent_pool_path, parent_pool)
            raise RuntimeError(
                f"No spawned child slots produced for task_index={task_index}; "
                "lineage cannot advance without spawn_child."
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
                    "task_id": task.task_id,
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
        if tool == "budget_status":
            result = read_budget_status(
                Path(str(context["budget_ledger_events"])),
                str(context["instance_uuid"]),
            )
            result = {"success": True, **result}
        elif tool == "submit_solution":
            result = _submit_solution(
                context=context,
                args=args,
            )
        elif tool == "spawn_child":
            raw_parent_budget = payload.get("parent_budget")
            parent_budget = raw_parent_budget if isinstance(raw_parent_budget, dict) else {}
            result = _spawn_child_continuation(
                context=context,
                args=args,
                parent_budget=parent_budget,
            )
        elif tool == "transfer_tokens":
            raw_source_budget = payload.get("source_budget")
            source_budget = raw_source_budget if isinstance(raw_source_budget, dict) else {}
            result = _transfer_tokens(
                context=context,
                args=args,
                source_budget=source_budget,
            )
        else:
            result = {
                "success": False,
                "reservation_committed": False,
                "transfer_committed": False,
                "error": f"unsupported dynamic tool: {tool}",
            }
    except BaseException as exc:
        result = {
            "success": False,
            "reservation_committed": False,
            "transfer_committed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    result = {
        **result,
        "success": bool(result.get("success")),
        "reservation_committed": bool(result.get("reservation_committed")),
        "transfer_committed": bool(result.get("transfer_committed")),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child-tool-handler":
        run_child_tool_handler(Path(sys.argv[2]).expanduser().resolve())
    else:
        main()

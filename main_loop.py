#!/usr/bin/env python3
"""Minimal RLVR episode loop.

Flow:
1) Sample one task from a Hugging Face RLVR-style dataset.
2) Create an ephemeral episode temp directory and write task metadata.
3) Run a tool-using worker (LLM + bash function tool) in that directory.
4) Evaluate rollout answer (`solution.json` preferred, `solution.md` fallback)
   against ground truth with reward util.
5) Append run metadata to a growing JSONL log.
6) Print a one-line summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.hf_datasets import HFDatasetDataLoader
from utils.openrouter import OpenRouterAPIError, bash_tool, call_openrouter_with_tools, get_tool_calls
from utils.reward import compute_rollout_reward
from utils.task_store import (
    compute_problem_uid,
    load_rollout_answer,
    redact_solution_fields,
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
        tid = _first_present(row, ["id", "task_id", "problem_id", "index"])

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
) -> Task:
    loader = HFDatasetDataLoader(
        dataset_name=dataset_name,
        split=split,
        config_name=config_name,
        batch_size=1,
        shuffle=True,
        seed=seed,
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
):
    loader = HFDatasetDataLoader(
        dataset_name=dataset_name,
        split=split,
        config_name=config_name,
        batch_size=1,
        shuffle=True,
        seed=seed,
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


def _run_bash_tool(command: str, working_directory: str, rollout_username: str | None = None) -> dict[str, Any]:
    try:
        git_identity = rollout_username or Path(working_directory).name
        env = os.environ.copy()
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
            timeout=30,
            env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "working_directory": working_directory,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + "\nCommand timed out after 30 seconds.",
            "working_directory": working_directory,
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


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


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


def _cleanup_rollout_shared_writes(root: Path, before: dict[Path, tuple[int, int]]) -> None:
    """Delete files created or modified in the shared workspace by a rollout."""
    if not root.exists():
        return

    after = _snapshot_workspace_files(root)
    dirty_paths = [rel for rel, sig in after.items() if before.get(rel) != sig]
    for rel in dirty_paths:
        target = root / rel
        if target.exists() and target.is_file():
            target.unlink()

    # Best-effort cleanup of now-empty directories under the shared root.
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue


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


def run_worker(
    *,
    api_key: str,
    model: str,
    question: str,
    task_id: str,
    workdir: Path,
    previous_rollout_dir: Path | None,
    next_rollout_dir: Path,
    archive_repo_dir: Path,
    shared_workspace_dir: Path,
    rollout_username: str,
) -> WorkerResult:
    """Run a multi-turn tool-calling worker loop and return final assistant text."""
    conversation: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        f"Working directory: {workdir}."
                    ),
                }
            ],
        }
    ]

    final_text = ""
    while True:
        try:
            response = call_openrouter_with_tools(
                api_key=api_key,
                model=model,
                input_items=conversation,
                tools=[bash_tool],
                tool_choice="auto",
                timeout=120,
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
                                    "Please retry with a valid run_bash function call."
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

            command = str(args.get("command", "")).strip()
            if call.get("name") != "run_bash":
                tool_result = {"error": f"unsupported tool '{call.get('name')}'"}
            elif not command:
                tool_result = {"error": "missing or malformed 'command' argument"}
            else:
                wd = str(args.get("working_directory") or workdir)
                try:
                    resolved_wd = Path(wd).resolve()
                    allowed_roots = [
                        workdir.resolve(),
                        next_rollout_dir.resolve(),
                        archive_repo_dir.resolve(),
                        shared_workspace_dir.resolve(),
                    ]
                    if previous_rollout_dir is not None:
                        allowed_roots.append(previous_rollout_dir.resolve())
                    safe_wd = str(workdir)
                    for root in allowed_roots:
                        if _is_within(resolved_wd, root):
                            safe_wd = str(resolved_wd)
                            break
                except Exception:
                    safe_wd = str(workdir)
                tool_result = _run_bash_tool(
                    command=command,
                    working_directory=safe_wd,
                    rollout_username=rollout_username,
                )

            conversation.append(call)
            conversation.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(tool_result),
                }
            )

    return WorkerResult(final_text=final_text, status="completed", stop_reason="final_message")


def persist_episode_outputs(temp_dir: Path, dest_root: Path, task_id: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_root / f"{ts}_{task_id}"
    shutil.copytree(temp_dir, dest, dirs_exist_ok=True)
    return dest


def append_run_log(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
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


def latest_successful_parent_pool_from_records(records: list[dict[str, Any]], num_rollouts: int) -> list[Path]:
    """Reconstruct the latest completed task's successful parent pool from run records."""
    by_task: dict[int, dict[int, dict[str, Any]]] = {}
    for rec in records:
        task_idx = rec.get("task_index")
        rollout_idx = rec.get("rollout_index")
        if not isinstance(task_idx, int) or not isinstance(rollout_idx, int):
            continue
        if rollout_idx < 0 or rollout_idx >= num_rollouts:
            continue
        by_task.setdefault(task_idx, {})[rollout_idx] = rec

    for task_idx in sorted(by_task, reverse=True):
        per_task = by_task[task_idx]
        if len(per_task) < num_rollouts:
            continue
        successes: list[Path] = []
        for rollout_idx in sorted(per_task):
            rec = per_task[rollout_idx]
            if not bool(rec.get("solved")):
                continue
            next_dir = rec.get("next_rollout_dir")
            if not isinstance(next_dir, str) or not next_dir:
                continue
            path = Path(next_dir)
            if path.exists():
                successes.append(path)
        if successes:
            return successes
    return []


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
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--split", default="train")
    parser.add_argument("--config-name", default=None)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument(
        "--num-rollouts",
        type=int,
        default=1,
        help="Number of rollouts to run per task.",
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
    parser.add_argument("--runs-log", default="logs/runs.jsonl")
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
        "--archive-repo-dir",
        default="archive/world_repo",
        help="Durable cross-lineage Git archive exposed to every rollout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.num_rollouts <= 0:
        raise ValueError("--num-rollouts must be > 0")
    rollout_usernames = [f"rollout_user_{idx:03d}" for idx in range(args.num_rollouts)]

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required.")

    archive_repo_dir = Path(args.archive_repo_dir).resolve()
    ensure_local_world_repo(archive_repo_dir)
    archive_git_lock = threading.Lock()

    rollout_root = Path(args.rollout_temp_root)
    rollout_root.mkdir(parents=True, exist_ok=True)
    archive_worktree_root = rollout_root / "archive_worktrees"

    parent_pool_path = rollout_root / "latest_parent_pool.json"
    shared_workspace_dir = rollout_root / "shared_workspace"
    shared_workspace_dir.mkdir(parents=True, exist_ok=True)

    parent_pool: list[Path] = []
    rng = random.Random(args.seed)

    def _build_parent_pool(successes: list[Path], target_size: int) -> list[Path]:
        """Construct the next-task parent pool.

        If we have fewer successful workspaces than rollouts, sample with replacement
        so every child rollout has an assigned parent.
        """
        if not successes or target_size <= 0:
            return []
        if len(successes) >= target_size:
            return rng.sample(successes, target_size)
        return [rng.choice(successes) for _ in range(target_size)]

    runs_log_path = Path(args.runs_log)
    task_store_dir = Path(args.task_store_dir)
    existing_records: list[dict[str, Any]] = []
    if not args.no_resume:
        all_records = load_existing_run_records(runs_log_path)
        existing_records = [
            rec
            for rec in all_records
            if rec.get("dataset_name") == args.dataset_name
            and rec.get("split") == args.split
            and rec.get("model") == args.model
            and rec.get("seed") == args.seed
            and rec.get("generation") == args.generation
            and rec.get("num_rollouts") == args.num_rollouts
            and rec.get("config_name") == args.config_name
        ]

    existing_by_task: dict[int, dict[int, dict[str, Any]]] = {}
    for rec in existing_records:
        task_idx = rec.get("task_index")
        rollout_idx = rec.get("rollout_index")
        if not isinstance(task_idx, int) or not isinstance(rollout_idx, int):
            continue
        if rollout_idx < 0 or rollout_idx >= args.num_rollouts:
            continue
        per_task = existing_by_task.setdefault(task_idx, {})
        existing = per_task.get(rollout_idx)
        if existing is None:
            per_task[rollout_idx] = rec

    if not args.no_resume:
        parent_pool = latest_successful_parent_pool_from_records(existing_records, args.num_rollouts)
        if parent_pool:
            save_parent_pool(parent_pool_path, parent_pool)
        else:
            parent_pool = load_parent_pool(parent_pool_path)

    def _next_step_task_index() -> int:
        eligible_indices = [idx for idx in existing_by_task if idx >= args.start_task_index]
        for idx in sorted(eligible_indices):
            if len(existing_by_task[idx]) < args.num_rollouts:
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
                ),
            )
        ]

    for task_index, task in tasks:
        successful_rollouts: list[Path] = []
        existing_task_records = existing_by_task.get(task_index, {})
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
        model_visible_row = redact_solution_fields(task.raw)

        if len(existing_task_records) >= args.num_rollouts:
            continue

        def _run_one_rollout(rollout_index: int) -> RolloutResult:
            existing = existing_task_records.get(rollout_index)
            if existing is not None:
                raise RuntimeError(f"rollout {rollout_index} already exists and should not have been submitted")

            rollout_username = rollout_usernames[rollout_index]
            sampled_parent: Path | None = (
                parent_pool[rollout_index % len(parent_pool)] if parent_pool else None
            )
            if sampled_parent is None and task_index > 0:
                raise RuntimeError(
                    "No parent seed available for non-bootstrap rollout; "
                    f"task_index={task_index} rollout_index={rollout_index}"
                )
            archive_worktree = create_archive_worktree(
                archive_repo_dir=archive_repo_dir,
                worktree_root=archive_worktree_root,
                branch=f"rollout/{task_index:06d}-{rollout_index:03d}-{_sanitize_for_path(task.task_id)}",
                git_lock=archive_git_lock,
            )
            archive_result: dict[str, Any] = {}

            temp_dir = Path(args.fixed_temp_dir) / f"{task_index:06d}" / f"rollout_{rollout_index:03d}"
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir.mkdir(parents=True, exist_ok=True)

            next_rollout_dir = rollout_root / (
                f"{task_index:06d}_{_sanitize_for_path(task.task_id)}_{_sanitize_for_path(rollout_username)}"
            )
            shutil.rmtree(next_rollout_dir, ignore_errors=True)
            next_rollout_dir.mkdir(parents=True, exist_ok=True)

            task_file = temp_dir / "task.json"
            task_file.write_text(
                json.dumps(
                    {
                        "problem_uid": problem_uid,
                        "dataset_row": model_visible_row,
                        "previous_rollout_dir": str(sampled_parent) if sampled_parent else None,
                        "next_rollout_dir": str(next_rollout_dir),
                        "archive_repo_dir": str(archive_worktree.path),
                        "archive_main_repo_dir": str(archive_repo_dir),
                        "shared_workspace_dir": str(shared_workspace_dir),
                        "rollout_username": rollout_username,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            try:
                try:
                    worker_result = run_worker(
                        api_key=api_key,
                        model=args.model,
                        question=task.question,
                        task_id=task.task_id,
                        workdir=temp_dir,
                        previous_rollout_dir=sampled_parent,
                        next_rollout_dir=next_rollout_dir,
                        archive_repo_dir=archive_worktree.path,
                        shared_workspace_dir=shared_workspace_dir,
                        rollout_username=rollout_username,
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
            if worker_result.status == "completed":
                reported_problem_uid, reported_task_id, submitted_answer = load_rollout_answer(
                    temp_dir,
                    worker_result.final_text,
                )
                reward = compute_rollout_reward(
                    submitted_answer=submitted_answer,
                    expected_task_id=task.task_id,
                    expected_problem_uid=problem_uid,
                    reported_task_id=reported_task_id,
                    reported_problem_uid=reported_problem_uid,
                    private_problem_path=private_problem_path,
                )
                solved = bool(reward >= 1.0)
            else:
                reported_problem_uid = None
                reported_task_id = None
                reward = 0.0
                solved = False

            output_dir = persist_episode_outputs(
                temp_dir,
                Path(args.outputs_dir),
                f"{task.task_id}_rollout_{rollout_index:03d}",
            )

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "generation": args.generation,
                "seed": args.seed,
                "task_index": task_index,
                "rollout_index": rollout_index,
                "rollout_username": rollout_username,
                "task_id": task.task_id,
                "problem_uid": problem_uid,
                "reported_problem_uid": reported_problem_uid,
                "reported_task_id": reported_task_id,
                "parent_rollout_dir": str(sampled_parent) if sampled_parent else None,
                "next_rollout_dir": str(next_rollout_dir),
                "worker_status": worker_result.status,
                "worker_stop_reason": worker_result.stop_reason,
                "worker_error_code": worker_result.error_code,
                "worker_error_message": worker_result.error_message,
                "solved": solved,
                "reward": reward,
                "output_path": str(output_dir),
                "private_problem_path": str(private_problem_path),
                "dataset_name": args.dataset_name,
                "split": args.split,
                "model": args.model,
                "num_rollouts": args.num_rollouts,
                "config_name": args.config_name,
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
                successful_dir=next_rollout_dir if solved else None,
                summary=summary,
                error=worker_result.error_message if worker_result.status == "error" else None,
            )

        missing_rollout_indices: list[int] = []
        for rollout_index in range(args.num_rollouts):
            existing = existing_task_records.get(rollout_index)
            if existing is not None:
                if bool(existing.get("solved")):
                    next_dir = existing.get("next_rollout_dir")
                    if isinstance(next_dir, str) and next_dir:
                        successful_rollouts.append(Path(next_dir))
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
                        results.append(
                            RolloutResult(
                                rollout_index=rollout_index,
                                record={
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "generation": args.generation,
                                    "seed": args.seed,
                                    "task_index": task_index,
                                    "rollout_index": rollout_index,
                                    "rollout_username": rollout_usernames[rollout_index],
                                    "task_id": task.task_id,
                                    "problem_uid": problem_uid,
                                    "reported_problem_uid": None,
                                    "reported_task_id": None,
                                    "parent_rollout_dir": None,
                                    "next_rollout_dir": None,
                                    "worker_status": "error",
                                    "worker_stop_reason": type(exc).__name__,
                                    "worker_error_code": None,
                                    "worker_error_message": str(exc),
                                    "solved": False,
                                    "reward": 0.0,
                                    "output_path": None,
                                    "private_problem_path": str(private_problem_path),
                                    "dataset_name": args.dataset_name,
                                    "split": args.split,
                                    "model": args.model,
                                    "num_rollouts": args.num_rollouts,
                                    "config_name": args.config_name,
                                },
                                successful_dir=None,
                                summary=(
                                    f"gen={args.generation} seed={args.seed} task_index={task_index} "
                                    f"rollout_index={rollout_index} rollout_username={rollout_usernames[rollout_index]} "
                                    f"task_id={task.task_id} solved=False output=None error={type(exc).__name__}"
                                ),
                                error=str(exc),
                            )
                        )

        _cleanup_rollout_shared_writes(shared_workspace_dir, shared_snapshot)

        for result in sorted(results, key=lambda item: item.rollout_index):
            append_run_log(runs_log_path, result.record)
            if result.successful_dir is not None:
                successful_rollouts.append(result.successful_dir)
            print(result.summary)

        if successful_rollouts:
            parent_pool = _build_parent_pool(successful_rollouts, args.num_rollouts)
            save_parent_pool(parent_pool_path, parent_pool)
        else:
            save_parent_pool(parent_pool_path, parent_pool)
            raise RuntimeError(
                f"No successful parent seeds produced for task_index={task_index}; "
                "lineage cannot advance without a parent seed."
            )

        failed_results = [result for result in results if result.error]
        if failed_results:
            details = "; ".join(
                f"rollout {result.rollout_index}: {result.error}"
                for result in sorted(failed_results, key=lambda item: item.rollout_index)
            )
            raise RuntimeError(f"One or more rollouts failed after logging results: {details}")


if __name__ == "__main__":
    main()

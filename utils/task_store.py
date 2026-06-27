"""Task-store and rollout artifact helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def _sanitize_for_path(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return safe or "unknown_task"


def compute_problem_uid(
    *,
    dataset_name: str,
    split: str,
    config_name: str | None,
    task_id: str,
    question: str,
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "dataset_name": dataset_name,
                "split": split,
                "config_name": config_name,
                "task_id": task_id,
                "question": question,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"problem_{digest}"


_SOLUTION_FIELD_PATTERNS = (
    "answer",
    "solution",
    "ground_truth",
    "target",
)


def _is_solution_like_field(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(token in normalized for token in _SOLUTION_FIELD_PATTERNS)


def redact_solution_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not _is_solution_like_field(str(k))}


def write_private_problem_record(*, task_store_dir: Path, problem_uid: str, row: dict[str, Any]) -> Path:
    task_store_dir.mkdir(parents=True, exist_ok=True)
    task_store_dir.chmod(0o700)
    path = task_store_dir / f"{_sanitize_for_path(problem_uid)}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(row, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    path.chmod(0o600)
    return path


def load_rollout_answer(temp_dir: Path, fallback_text: str) -> tuple[str | None, str | None, str]:
    solution_json = temp_dir / "solution.json"
    if solution_json.exists():
        try:
            payload = json.loads(solution_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            problem_uid = payload.get("problem_uid")
            task_id = payload.get("task_id")
            answer = payload.get("answer")
            return (
                str(problem_uid) if problem_uid is not None else None,
                str(task_id) if task_id is not None else None,
                str(answer) if answer is not None else "",
            )

    solution_md = temp_dir / "solution.md"
    if solution_md.exists():
        return None, None, solution_md.read_text(encoding="utf-8")

    return None, None, fallback_text if fallback_text else "\\boxed{}"

"""SuperGPQA submit_solution grading shared by local tool transports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.budget_ledger import append_budget_event, read_budget_status
from utils.reward import compute_rollout_reward


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


def solve_reward_credit_total(events_path: Path, instance_uuid: str) -> int:
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


def _solve_reward_credited_problem_uids(
    events_path: Path, instance_uuid: str
) -> set[str]:
    credited: set[str] = set()
    for event in _iter_budget_events(events_path):
        if event.get("event_type") != "solve_reward_credit":
            continue
        if event.get("instance_uuid") != instance_uuid:
            continue
        metadata = event.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        problem_uid = metadata.get("problem_uid")
        if isinstance(problem_uid, str) and problem_uid:
            credited.add(problem_uid)
    return credited


def solution_scored_events(
    events_path: Path, instance_uuid: str
) -> list[dict[str, Any]]:
    return [
        event
        for event in _iter_budget_events(events_path)
        if event.get("event_type") == "solution_scored"
        and event.get("instance_uuid") == instance_uuid
    ]


def latest_solution_scored_event(
    events_path: Path, instance_uuid: str
) -> dict[str, Any] | None:
    events = solution_scored_events(events_path, instance_uuid)
    return events[-1] if events else None


def _parse_arguments(
    args: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    raw_uuid = args.get(
        "uuid",
        args.get("problem_uuid", args.get("problemUid", args.get("problem_uid"))),
    )
    submitted_uuid = str(raw_uuid).strip() if raw_uuid is not None else None
    if not submitted_uuid:
        return None, None, "submit_solution requires a non-empty string uuid"
    answer = args.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None, None, "submit_solution requires a non-empty string answer"
    return submitted_uuid, answer.strip(), None


def _problem_for_uuid(
    context: dict[str, Any], submitted_uuid: str
) -> dict[str, Any] | None:
    records = context.get("problem_pool_records")
    if not isinstance(records, list):
        return None
    for payload in records:
        if not isinstance(payload, dict):
            continue
        problem_uid = payload.get("problem_uid")
        visible_uuid = payload.get("uuid", problem_uid)
        if submitted_uuid not in {str(problem_uid or ""), str(visible_uuid or "")}:
            continue
        try:
            task_index = int(payload["task_index"])
        except (KeyError, TypeError, ValueError):
            return None
        task_id = payload.get("task_id")
        task_markdown = payload.get("task_markdown")
        private_problem_path = payload.get("private_problem_path")
        if not all(
            isinstance(value, str) and value
            for value in (task_id, problem_uid, task_markdown, private_problem_path)
        ):
            return None
        return {
            "task_index": task_index,
            "task_id": task_id,
            "problem_uid": problem_uid,
            "task_markdown": task_markdown,
            "private_problem_path": private_problem_path,
        }
    return None


def submit_solution(
    *, context: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    """Score one SuperGPQA answer and append the existing ledger events."""

    submitted_uuid, answer, error = _parse_arguments(args)
    if error is not None or submitted_uuid is None or answer is None:
        return {"success": False, "error": error or "invalid submit_solution arguments"}

    instance_uuid = str(context["instance_uuid"])
    budget_ledger_events = Path(str(context["budget_ledger_events"]))
    problem = _problem_for_uuid(context, submitted_uuid)
    if problem is None:
        return {
            "success": False,
            "error": "submitted uuid is not in this iteration's shared problem pool copy",
            "submitted_uuid": submitted_uuid,
        }
    problem_uid = str(problem["problem_uid"])
    task_id = str(problem["task_id"])
    private_problem_path = Path(str(problem["private_problem_path"]))
    reward = compute_rollout_reward(
        submitted_answer=answer,
        expected_task_id=task_id,
        expected_problem_uid=problem_uid,
        reported_task_id=None,
        reported_problem_uid=submitted_uuid,
        private_problem_path=private_problem_path,
    )
    solved = bool(reward >= 1.0)
    try:
        configured_credit_tokens = int(
            context.get("solve_reward_token_credit_tokens") or 0
        )
    except (TypeError, ValueError):
        configured_credit_tokens = 0
    credited_problem_uids = _solve_reward_credited_problem_uids(
        budget_ledger_events, instance_uuid
    )
    credited_tokens = (
        configured_credit_tokens
        if solved and problem_uid not in credited_problem_uids
        else 0
    )

    metadata = {
        "generation": context["generation"],
        "seed": context["seed"],
        "task_index": context["task_index"],
        "problem_task_index": problem["task_index"],
        "rollout_index": context["rollout_index"],
        "rollout_username": context["rollout_username"],
        "task_id": task_id,
        "problem_uid": problem_uid,
        "private_problem_path": str(private_problem_path),
        "task_markdown": problem["task_markdown"],
        "submitted_uuid": submitted_uuid,
        "reported_problem_uid": submitted_uuid,
        "reported_task_id": None,
        "submitted_answer": answer,
        "solved": solved,
        "reward_credit_claimed": credited_tokens > 0,
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
                "problem_task_index": problem["task_index"],
                "rollout_index": context["rollout_index"],
                "rollout_username": context["rollout_username"],
                "task_id": task_id,
                "problem_uid": problem_uid,
                "reward": reward,
            },
        )
    total_credited_tokens = solve_reward_credit_total(
        budget_ledger_events, instance_uuid
    )
    return {
        "success": True,
        "correct": solved,
        "solved": solved,
        "reward_credit_claimed": credited_tokens > 0,
        "reward": reward,
        "credited_tokens": credited_tokens,
        "total_credited_tokens": total_credited_tokens,
        "submitted_uuid": submitted_uuid,
        "budget_status": read_budget_status(budget_ledger_events, instance_uuid),
    }

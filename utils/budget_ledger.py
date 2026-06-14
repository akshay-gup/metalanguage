"""Append-only token budget ledger helpers for rollout instances."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
from typing import Any
import uuid


PROJECTION_VERSION = 1


def new_instance_uuid() -> str:
    return str(uuid.uuid4())


def budget_projection_path(events_path: Path) -> Path:
    return events_path.with_suffix(".projection.json")


def append_budget_event(
    events_path: Path,
    *,
    event_type: str,
    instance_uuid: str,
    amount_tokens: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = append_budget_events(
        events_path,
        [
            {
                "event_type": event_type,
                "instance_uuid": instance_uuid,
                "amount_tokens": amount_tokens,
                "metadata": metadata or {},
            }
        ],
    )
    return events[0]


def append_budget_events(events_path: Path, event_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return budget_ledger_transaction(
        events_path,
        debit_instance_uuid=None,
        required_tokens=0,
        build_event_specs=lambda _status: event_specs,
    )["events"]


def budget_ledger_transaction(
    events_path: Path,
    *,
    debit_instance_uuid: str | None,
    required_tokens: int,
    build_event_specs: Callable[[dict[str, Any]], list[dict[str, Any]]],
    debit_status_floor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if required_tokens < 0:
        raise ValueError("required_tokens must be >= 0")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path = budget_projection_path(events_path)
    lock_path = events_path.with_suffix(events_path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        projection = _load_or_rebuild_projection_locked(events_path, projection_path)
        status_before = (
            budget_status_from_projection(projection, debit_instance_uuid)
            if debit_instance_uuid is not None
            else {}
        )
        if debit_instance_uuid is not None and debit_status_floor is not None:
            status_before = _merge_debit_status_floor(status_before, debit_status_floor)
        if debit_instance_uuid is not None and required_tokens > 0:
            remaining = status_before.get("tokens_remaining")
            if remaining is None:
                return {
                    "success": False,
                    "error": "token budget is not configured",
                    "budget_status": status_before,
                    "events": [],
                }
            if required_tokens > int(remaining):
                return {
                    "success": False,
                    "error": "insufficient token budget",
                    "requested_amount_tokens": required_tokens,
                    "budget_status": status_before,
                    "events": [],
                }

        event_specs = build_event_specs(status_before)
        events = [_make_budget_event(spec) for spec in event_specs]
        if events:
            with events_path.open("a", encoding="utf-8") as fh:
                for event in events:
                    fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            for event in events:
                _apply_event_to_projection(projection, event)
        _write_projection_locked(events_path, projection_path, projection)
        status_after = (
            budget_status_from_projection(projection, debit_instance_uuid)
            if debit_instance_uuid is not None
            else {}
        )
        if debit_instance_uuid is not None and debit_status_floor is not None:
            status_after = _merge_debit_status_floor(status_after, debit_status_floor)
        return {
            "success": True,
            "budget_status_before": status_before,
            "budget_status_after": status_after,
            "events": events,
        }


def read_budget_status(events_path: Path, instance_uuid: str) -> dict[str, Any]:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    projection_path = budget_projection_path(events_path)
    lock_path = events_path.with_suffix(events_path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        projection = _load_or_rebuild_projection_locked(events_path, projection_path)
        _write_projection_locked(events_path, projection_path, projection)
        return budget_status_from_projection(projection, instance_uuid)


def budget_status_from_projection(projection: dict[str, Any], instance_uuid: str) -> dict[str, Any]:
    account = _projection_account(projection, instance_uuid)
    rollout_budget = account.get("rollout_token_budget_tokens")
    transferred_in = _int_token(account.get("tokens_transferred_in"))
    transferred_out = _int_token(account.get("tokens_transferred_out"))
    tokens_spent = _int_token(account.get("tokens_spent"))
    reserved_child_tokens = _int_token(account.get("tokens_reserved_for_children"))
    effective_budget = (
        int(rollout_budget) + transferred_in
        if isinstance(rollout_budget, int)
        else None
    )
    tokens_remaining = (
        max(0, effective_budget - tokens_spent - reserved_child_tokens - transferred_out)
        if effective_budget is not None
        else None
    )
    return {
        "budget_configured": rollout_budget is not None,
        "rollout_token_budget_tokens": rollout_budget,
        "effective_rollout_token_budget_tokens": effective_budget,
        "tokens_spent": tokens_spent,
        "tokens_reserved_for_children": reserved_child_tokens,
        "tokens_transferred_in": transferred_in,
        "tokens_transferred_out": transferred_out,
        "tokens_remaining": tokens_remaining,
    }


def _merge_debit_status_floor(
    projected_status: dict[str, Any],
    debit_status_floor: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(projected_status)
    for key in (
        "tokens_spent",
        "tokens_reserved_for_children",
        "tokens_transferred_out",
    ):
        merged[key] = max(_int_token(projected_status.get(key)), _int_token(debit_status_floor.get(key)))
    rollout_budget = projected_status.get("rollout_token_budget_tokens")
    transferred_in = _int_token(projected_status.get("tokens_transferred_in"))
    effective_budget = (
        int(rollout_budget) + transferred_in
        if isinstance(rollout_budget, int)
        else None
    )
    merged["effective_rollout_token_budget_tokens"] = effective_budget
    merged["tokens_remaining"] = (
        max(
            0,
            effective_budget
            - merged["tokens_spent"]
            - merged["tokens_reserved_for_children"]
            - merged["tokens_transferred_out"],
        )
        if effective_budget is not None
        else None
    )
    return merged


def _make_budget_event(spec: dict[str, Any]) -> dict[str, Any]:
    amount_tokens = _int_token(spec.get("amount_tokens"))
    if amount_tokens < 0:
        raise ValueError("amount_tokens must be >= 0")
    instance_uuid = spec.get("instance_uuid")
    if not isinstance(instance_uuid, str) or not instance_uuid:
        raise ValueError("budget event requires instance_uuid")
    event_type = spec.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("budget event requires event_type")
    metadata = spec.get("metadata")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "instance_uuid": instance_uuid,
        "amount_tokens": amount_tokens,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _empty_projection() -> dict[str, Any]:
    return {
        "version": PROJECTION_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ledger_size_bytes": 0,
        "accounts": {},
    }


def _projection_account(projection: dict[str, Any], instance_uuid: str) -> dict[str, Any]:
    accounts = projection.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}
        projection["accounts"] = accounts
    account = accounts.get(instance_uuid)
    if not isinstance(account, dict):
        account = {
            "instance_uuid": instance_uuid,
            "rollout_token_budget_tokens": None,
            "tokens_spent": 0,
            "tokens_reserved_for_children": 0,
            "tokens_transferred_in": 0,
            "tokens_transferred_out": 0,
        }
        accounts[instance_uuid] = account
    return account


def _load_or_rebuild_projection_locked(events_path: Path, projection_path: Path) -> dict[str, Any]:
    ledger_size = events_path.stat().st_size if events_path.exists() else 0
    try:
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return _rebuild_projection_locked(events_path, ledger_size)
    if not isinstance(projection, dict):
        return _rebuild_projection_locked(events_path, ledger_size)
    if projection.get("version") != PROJECTION_VERSION:
        return _rebuild_projection_locked(events_path, ledger_size)
    try:
        projected_ledger_size = int(projection.get("ledger_size_bytes"))
    except (TypeError, ValueError):
        return _rebuild_projection_locked(events_path, ledger_size)
    if projected_ledger_size != ledger_size:
        return _rebuild_projection_locked(events_path, ledger_size)
    return projection


def _rebuild_projection_locked(events_path: Path, ledger_size: int) -> dict[str, Any]:
    projection = _empty_projection()
    if events_path.exists():
        with events_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    _apply_event_to_projection(projection, event)
    projection["ledger_size_bytes"] = ledger_size
    return projection


def _write_projection_locked(events_path: Path, projection_path: Path, projection: dict[str, Any]) -> None:
    projection_path.parent.mkdir(parents=True, exist_ok=True)
    projection["version"] = PROJECTION_VERSION
    projection["updated_at"] = datetime.now(timezone.utc).isoformat()
    projection["ledger_size_bytes"] = events_path.stat().st_size if events_path.exists() else 0
    temp_path = projection_path.with_suffix(projection_path.suffix + f".{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(projection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, projection_path)


def _apply_event_to_projection(projection: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = event.get("event_type")
    instance_uuid = event.get("instance_uuid")
    if not isinstance(event_type, str) or not isinstance(instance_uuid, str) or not instance_uuid:
        return
    amount_tokens = _int_token(event.get("amount_tokens"))
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    account = _projection_account(projection, instance_uuid)

    if event_type == "instance_created":
        budget = _metadata_budget(metadata)
        if budget is not None:
            account["rollout_token_budget_tokens"] = budget
    elif event_type == "token_usage":
        account["tokens_spent"] = _int_token(account.get("tokens_spent")) + amount_tokens
    elif event_type == "budget_reserved":
        account["tokens_reserved_for_children"] = (
            _int_token(account.get("tokens_reserved_for_children")) + amount_tokens
        )
    elif event_type == "budget_transferred_out":
        account["tokens_transferred_out"] = (
            _int_token(account.get("tokens_transferred_out")) + amount_tokens
        )
    elif event_type == "budget_transferred_in":
        account["tokens_transferred_in"] = (
            _int_token(account.get("tokens_transferred_in")) + amount_tokens
        )
    elif event_type == "solve_reward_credit":
        account["tokens_transferred_in"] = (
            _int_token(account.get("tokens_transferred_in")) + amount_tokens
        )
    elif event_type == "budget_transferred":
        account["tokens_transferred_out"] = (
            _int_token(account.get("tokens_transferred_out")) + amount_tokens
        )
        target_instance_uuid = metadata.get("target_instance_uuid")
        if isinstance(target_instance_uuid, str) and target_instance_uuid:
            target = _projection_account(projection, target_instance_uuid)
            target["tokens_transferred_in"] = (
                _int_token(target.get("tokens_transferred_in")) + amount_tokens
            )
    elif event_type == "child_spawned":
        account["tokens_reserved_for_children"] = (
            _int_token(account.get("tokens_reserved_for_children")) + amount_tokens
        )
        child_instance_uuid = metadata.get("child_instance_uuid")
        if isinstance(child_instance_uuid, str) and child_instance_uuid:
            child = _projection_account(projection, child_instance_uuid)
            budget = _metadata_budget(metadata)
            if budget is None and amount_tokens > 0:
                budget = amount_tokens
            if budget is not None:
                child["rollout_token_budget_tokens"] = budget


def _metadata_budget(metadata: dict[str, Any]) -> int | None:
    for key in ("rollout_token_budget_tokens", "initial_budget_tokens", "assigned_budget_tokens"):
        value = metadata.get(key)
        try:
            budget = int(value)
        except (TypeError, ValueError):
            continue
        if budget > 0:
            return budget
    return None


def _int_token(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

"""Append-only token budget ledger helpers for rollout instances."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid


def new_instance_uuid() -> str:
    return str(uuid.uuid4())


def append_budget_event(
    events_path: Path,
    *,
    event_type: str,
    instance_uuid: str,
    amount_tokens: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if amount_tokens < 0:
        raise ValueError("amount_tokens must be >= 0")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "instance_uuid": instance_uuid,
        "amount_tokens": amount_tokens,
        "metadata": metadata or {},
    }
    with events_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event

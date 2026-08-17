"""Append-only benchmark event log helpers.

The log stores benchmark provenance, submissions, and official command
accounting. It deliberately stores no rollout resource state.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def new_instance_uuid() -> str:
    return str(uuid.uuid4())


def iter_benchmark_events(events_path: Path) -> list[dict[str, Any]]:
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


def append_benchmark_event(
    events_path: Path,
    *,
    event_type: str,
    instance_uuid: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = benchmark_event_transaction(
        events_path,
        lambda _events: [
            {
                "event_type": event_type,
                "instance_uuid": instance_uuid,
                "metadata": metadata or {},
            }
        ],
    )
    return events[0]


def benchmark_event_transaction(
    events_path: Path,
    build_event_specs: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Build and append events while holding the log's exclusive file lock."""

    events_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = events_path.with_name(f"{events_path.name}.lock")
    with _private_lock(lock_path):
        existing = iter_benchmark_events(events_path)
        specs = build_event_specs(existing)
        events = [_make_event(spec) for spec in specs]
        if events:
            _append_events_locked(events_path, events)
        return events


def _make_event(spec: dict[str, Any]) -> dict[str, Any]:
    instance_uuid = spec.get("instance_uuid")
    event_type = spec.get("event_type")
    if not isinstance(instance_uuid, str) or not instance_uuid:
        raise ValueError("benchmark event requires instance_uuid")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("benchmark event requires event_type")
    metadata = spec.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("benchmark event metadata must be an object")
    return {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "instance_uuid": instance_uuid,
        "metadata": metadata,
    }


def _append_events_locked(events_path: Path, events: list[dict[str, Any]]) -> None:
    descriptor = os.open(events_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _private_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

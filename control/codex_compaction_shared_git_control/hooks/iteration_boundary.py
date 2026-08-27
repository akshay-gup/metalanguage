#!/usr/bin/env python3
"""Stock Codex Stop/PostCompact hook for one automatic-compaction window."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any


CONTINUATION_INPUT = "Continue until the next automatic compaction boundary."
BOUNDARY_STOP_REASON = "Automatic compaction boundary reached."


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def append_event(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def state_directory() -> Path:
    raw = os.environ.get("CONTROL_ROLLOUT_STATE_DIR")
    if not raw:
        raise RuntimeError("CONTROL_ROLLOUT_STATE_DIR is not set")
    path = Path(raw)
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("rollout state directory is not an absolute real directory")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise RuntimeError("rollout state directory path changed")
    return resolved


def event_digest(event: dict[str, Any]) -> str:
    safe = {
        "hook_event_name": event.get("hook_event_name"),
        "session_id": event.get("session_id"),
        "turn_id": event.get("turn_id"),
        "trigger": event.get("trigger"),
        "model": event.get("model"),
    }
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def handle(event: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    event_name = event.get("hook_event_name")
    if event_name not in {"Stop", "PostCompact"}:
        raise RuntimeError(f"unsupported hook event: {event_name!r}")

    lock_path = state_dir / "boundary.lock"
    lock_path.touch(mode=0o600, exist_ok=True)
    with lock_path.open("r+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        counter_path = state_dir / "compaction_counter.json"
        boundary_path = state_dir / "boundary.json"
        counter = load_json(counter_path)
        boundary = load_json(boundary_path)
        count = counter.get("count")
        target = boundary.get("target_count")
        if not isinstance(count, int) or count < 0:
            raise RuntimeError("invalid compaction counter")
        if not isinstance(target, int) or target != count + 1:
            raise RuntimeError("invalid or stale compaction target")

        record: dict[str, Any] = {
            "at": utc_now(),
            "event": event_name,
            "event_digest": event_digest(event),
            "session_id": event.get("session_id"),
            "turn_id": event.get("turn_id"),
        }

        if event_name == "PostCompact":
            if event.get("trigger") != "auto":
                raise RuntimeError("PostCompact hook received a non-auto trigger")
            count += 1
            atomic_json(
                counter_path,
                {
                    "count": count,
                    "last_automatic_compaction_at": record["at"],
                    "last_session_id": event.get("session_id"),
                    "last_turn_id": event.get("turn_id"),
                },
            )
            record["count_after"] = count
            append_event(state_dir / "hook_events.jsonl", record)
            return {"continue": False, "stopReason": BOUNDARY_STOP_REASON}

        record["count"] = count
        record["target_count"] = target
        append_event(state_dir / "hook_events.jsonl", record)
        if count < target:
            return {"decision": "block", "reason": CONTINUATION_INPUT}
        return {"continue": False, "stopReason": BOUNDARY_STOP_REASON}


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input must be a JSON object")
        result = handle(event, state_directory())
    except Exception as exc:
        print(f"iteration boundary hook failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

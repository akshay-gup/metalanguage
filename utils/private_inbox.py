"""Supervisor-owned private inbox support for open-ended managed rollouts."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


PRIVATE_INBOX_CAPABILITY_IDENTITY = (
    "metalanguage-v3.7-codex-open-ended-private-inbox-v1"
)
ROLLOUT_HUMAN_NAMES = (
    "Daniel",
    "Noah",
    "Elizabeth",
    "George",
    "Eva",
    "Eleanor",
    "Zoe",
    "Oliver",
)


@dataclass(frozen=True)
class PrivateInboxConfig:
    sender: str
    own_inbox: Path
    recipient_inboxes: Mapping[str, Path]
    state_path: Path
    protected_read_paths: tuple[Path, ...] = ()

    @property
    def capability_identity(self) -> str:
        return PRIVATE_INBOX_CAPABILITY_IDENTITY

    def to_context(self) -> dict[str, Any]:
        return {
            "capability_identity": self.capability_identity,
            "sender": self.sender,
            "own_inbox": str(self.own_inbox),
            "recipient_inboxes": {
                recipient: str(path)
                for recipient, path in self.recipient_inboxes.items()
            },
            "state_path": str(self.state_path),
        }


def private_inbox_enabled(
    benchmark: str,
    worker_backend: str,
) -> bool:
    return benchmark == "open-ended" and worker_backend in {"codex", "opencode"}


def initialize_private_inboxes(
    rollout_workdirs: Mapping[int, Path],
    *,
    state_path: Path,
    protected_read_paths: tuple[Path, ...] = (),
) -> dict[int, PrivateInboxConfig]:
    indices = sorted(rollout_workdirs)
    if any(index < 0 or index >= len(ROLLOUT_HUMAN_NAMES) for index in indices):
        raise ValueError(
            "private inbox rollout indices must use the fixed human roster 0 through 7"
        )
    if any(not path.is_absolute() for path in protected_read_paths):
        raise ValueError("private inbox protected read paths must be absolute")

    inboxes: dict[int, Path] = {}
    for index in indices:
        workdir = rollout_workdirs[index]
        if not workdir.is_absolute() or not workdir.is_dir():
            raise ValueError("private inbox workspaces must be existing absolute directories")
        inbox = workdir / "messages"
        if inbox.exists() or inbox.is_symlink():
            raise ValueError("private inbox path must not already exist")
        inbox.mkdir(mode=0o700)
        inboxes[index] = inbox

    configs: dict[int, PrivateInboxConfig] = {}
    for index in indices:
        sender = ROLLOUT_HUMAN_NAMES[index]
        recipients = {
            ROLLOUT_HUMAN_NAMES[other_index]: inboxes[other_index]
            for other_index in indices
            if other_index != index
        }
        configs[index] = PrivateInboxConfig(
            sender=sender,
            own_inbox=inboxes[index],
            recipient_inboxes=recipients,
            state_path=state_path,
            protected_read_paths=protected_read_paths,
        )
    return configs


def cleanup_private_inboxes(configs: Mapping[int, PrivateInboxConfig]) -> None:
    state_paths: set[Path] = set()
    for config in configs.values():
        state_paths.add(config.state_path)
        inbox = config.own_inbox
        if inbox.name != "messages" or not inbox.is_absolute():
            raise ValueError("refusing to clean an invalid private inbox path")
        if inbox.is_symlink():
            inbox.unlink()
        elif inbox.exists():
            shutil.rmtree(inbox)
    for state_path in state_paths:
        for path in (state_path, state_path.with_suffix(state_path.suffix + ".lock")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _message_failure(
    error_code: str,
    *,
    retryable: bool,
) -> dict[str, Any]:
    return {
        "success": False,
        "status": "rejected",
        "retryable": retryable,
        "error_code": error_code,
        "error": "message was not delivered",
    }


def _message_success(
    *,
    sender: str,
    recipient: str,
    size: int,
    sequence: int,
    duplicate: bool,
    idempotent: bool,
) -> dict[str, Any]:
    return {
        "success": True,
        "status": "delivered",
        "sender": sender,
        "recipient": recipient,
        "size": size,
        "sequence": sequence,
        "duplicate": duplicate,
        "idempotent": idempotent,
    }


def _validated_message(
    args: dict[str, Any],
    *,
    sender: str,
    recipients: Mapping[str, Path],
) -> tuple[str | None, bytes | None, int | None, str | None]:
    if sorted(args) != ["message", "recipient"]:
        return None, None, None, "invalid_message_arguments"

    recipient = args.get("recipient")
    if not isinstance(recipient, str):
        return None, None, None, "invalid_recipient"
    if recipient == sender:
        return None, None, None, "self_recipient_forbidden"
    if recipient not in recipients:
        return None, None, None, "invalid_recipient"

    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        return recipient, None, None, "invalid_message"
    try:
        message_bytes = message.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return recipient, None, None, "invalid_message_encoding"
    size = len(message_bytes)
    if "\x00" in message or any(unicodedata.category(char) == "Cs" for char in message):
        return recipient, None, size, "invalid_message_controls"
    disallowed_controls = sum(
        1
        for char in message
        if char not in "\n\r\t" and unicodedata.category(char) in {"Cc", "Cf"}
    )
    if disallowed_controls > 4 or (
        disallowed_controls and disallowed_controls * 20 > len(message)
    ):
        return recipient, None, size, "invalid_message_controls"
    return recipient, message_bytes, size, None


def _valid_call_id(call_id: Any) -> str | None:
    if not isinstance(call_id, str) or not 1 <= len(call_id) <= 256:
        return None
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in call_id):
        return None
    return call_id


def _load_message_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "format": "metalanguage-private-inbox-state",
            "version": 1,
            "capability_identity": PRIVATE_INBOX_CAPABILITY_IDENTITY,
            "next_sequence": 1,
            "calls": {},
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("private inbox state is unreadable") from exc
    if not isinstance(state, dict) or state.get("format") != "metalanguage-private-inbox-state":
        raise RuntimeError("private inbox state is incompatible")
    if state.get("version") != 1 or state.get("capability_identity") != PRIVATE_INBOX_CAPABILITY_IDENTITY:
        raise RuntimeError("private inbox state is incompatible")
    if not isinstance(state.get("calls"), dict):
        raise RuntimeError("private inbox state is incompatible")
    return state


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        with temp_path.open("x", encoding="utf-8") as handle:
            os.chmod(temp_path, 0o600)
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _message_file_bytes(sender: str, message: bytes) -> bytes:
    suffix = b"" if message.endswith(b"\n") else b"\n"
    return f"# Message from {sender}\n\n".encode("utf-8") + message + suffix


def _create_message_file_atomic(path: Path, content: bytes) -> None:
    temp_path = path.parent / f".pending.{os.getpid()}.{secrets.token_hex(8)}"
    file_descriptor: int | None = None
    try:
        file_descriptor = os.open(
            temp_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, path, follow_symlinks=False)
        os.chmod(path, 0o444)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _append_progress(context: dict[str, Any], fields: dict[str, Any]) -> None:
    progress_path = Path(str(context.get("progress_log", "")))
    if not progress_path.is_absolute():
        return
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = progress_path.with_suffix(progress_path.suffix + ".private-inbox.lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        with progress_path.open("a", encoding="utf-8") as progress_handle:
            progress_handle.write(json.dumps(fields, ensure_ascii=False) + "\n")


def deliver_private_message(
    *,
    context: dict[str, Any],
    args: dict[str, Any],
    call_id: Any,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    private = context.get("private_inbox")
    if not isinstance(private, dict) or private.get("capability_identity") != PRIVATE_INBOX_CAPABILITY_IDENTITY:
        return _message_failure("private_inbox_unavailable", retryable=False)
    sender = private.get("sender")
    raw_recipients = private.get("recipient_inboxes")
    if sender not in ROLLOUT_HUMAN_NAMES or not isinstance(raw_recipients, dict):
        return _message_failure("private_inbox_context_invalid", retryable=False)
    if sender in raw_recipients or any(
        recipient not in ROLLOUT_HUMAN_NAMES for recipient in raw_recipients
    ):
        return _message_failure("private_inbox_context_invalid", retryable=False)
    recipients = {
        recipient: Path(path)
        for recipient, path in raw_recipients.items()
        if isinstance(path, str)
    }
    if len(recipients) != len(raw_recipients):
        return _message_failure("private_inbox_context_invalid", retryable=False)

    recipient, message_bytes, size, validation_error = _validated_message(
        args,
        sender=sender,
        recipients=recipients,
    )

    def notify(status: str, *, sequence: int | None = None) -> None:
        fields = {
            "sender": sender,
            "recipient": recipient,
            "size": size,
            "sequence": sequence,
            "status": status,
        }
        if progress_callback is not None:
            progress_callback(fields)
        else:
            _append_progress(context, fields)

    if validation_error is not None or recipient is None or message_bytes is None or size is None:
        notify(f"rejected_{validation_error or 'invalid_message'}")
        return _message_failure(validation_error or "invalid_message", retryable=True)

    target_inbox = recipients[recipient]
    if (
        not target_inbox.is_absolute()
        or target_inbox.name != "messages"
        or target_inbox.is_symlink()
        or not target_inbox.is_dir()
    ):
        notify("failed")
        return _message_failure("recipient_inbox_unavailable", retryable=True)

    state_path = Path(str(private.get("state_path", "")))
    if not state_path.is_absolute():
        notify("failed")
        return _message_failure("private_inbox_context_invalid", retryable=False)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stable_call_id = _valid_call_id(call_id)
    call_key = (
        hashlib.sha256(f"{sender}\0{stable_call_id}".encode("utf-8")).hexdigest()
        if stable_call_id is not None
        else None
    )
    message_sha256 = hashlib.sha256(message_bytes).hexdigest()
    content = _message_file_bytes(sender, message_bytes)

    with lock_path.open("a", encoding="utf-8") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            state = _load_message_state(state_path)
            calls = state["calls"]
            existing = calls.get(call_key) if call_key is not None else None
            if existing is not None:
                if not isinstance(existing, dict) or any(
                    existing.get(key) != expected
                    for key, expected in (
                        ("sender", sender),
                        ("recipient", recipient),
                        ("message_sha256", message_sha256),
                        ("size", size),
                    )
                ):
                    notify("rejected_call_id_conflict")
                    return _message_failure("call_id_conflict", retryable=False)
                sequence = int(existing["sequence"])
                message_path = target_inbox / f"{sequence:06d}_{sender}.md"
                if message_path.exists():
                    try:
                        matches = message_path.is_file() and not message_path.is_symlink() and message_path.read_bytes() == content
                    except OSError:
                        matches = False
                    if not matches:
                        notify("failed", sequence=sequence)
                        return _message_failure("delivery_conflict", retryable=False)
                else:
                    try:
                        _create_message_file_atomic(message_path, content)
                    except OSError:
                        notify("failed", sequence=sequence)
                        return _message_failure("delivery_failed", retryable=True)
                existing["status"] = "delivered"
                _write_json_atomic(state_path, state)
                notify("delivered_duplicate", sequence=sequence)
                return _message_success(
                    sender=sender,
                    recipient=recipient,
                    size=size,
                    sequence=sequence,
                    duplicate=True,
                    idempotent=True,
                )

            sequence = int(state.get("next_sequence", 1))
            if sequence < 1:
                notify("failed")
                return _message_failure("private_inbox_state_invalid", retryable=False)
            call_record = {
                "sender": sender,
                "recipient": recipient,
                "message_sha256": message_sha256,
                "size": size,
                "sequence": sequence,
                "status": "pending",
                "idempotent": stable_call_id is not None,
            }
            if call_key is not None:
                calls[call_key] = call_record
            state["next_sequence"] = sequence + 1
            _write_json_atomic(state_path, state)

            message_path = target_inbox / f"{sequence:06d}_{sender}.md"
            try:
                _create_message_file_atomic(message_path, content)
            except OSError:
                notify("failed", sequence=sequence)
                return _message_failure("delivery_failed", retryable=True)
            call_record["status"] = "delivered"
            _write_json_atomic(state_path, state)
        except (OSError, RuntimeError, TypeError, ValueError):
            notify("failed")
            return _message_failure("private_inbox_state_failure", retryable=True)

    notify("delivered", sequence=sequence)
    return _message_success(
        sender=sender,
        recipient=recipient,
        size=size,
        sequence=sequence,
        duplicate=False,
        idempotent=stable_call_id is not None,
    )

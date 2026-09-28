"""Backend-independent child slot handling without the episode loop imports."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.archive_contract import shared_archives_metadata
from utils.benchmark_driver import BenchmarkItemRef, active_benchmark_item
from utils.benchmark_events import new_instance_uuid
from utils.directory_agents import (
    ensure_directory_agents_file,
    ensure_directory_tree_agents_files,
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


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


def append_progress_log(log_path: Path, lock: threading.Lock, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with lock:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


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
        return None, "spawn_child requires a workspace_dir containing AGENTS.md"
    workdir = Path(str(context["workdir"])).resolve()
    raw_path = Path(workspace_dir).expanduser()
    candidate = raw_path.resolve() if raw_path.is_absolute() else (workdir / raw_path).resolve()
    if candidate == workdir or not _is_within(candidate, workdir):
        return None, "workspace_dir must be a workspace-local directory, not the rollout workspace root"
    if not candidate.is_dir():
        return None, f"workspace_dir is not a directory: {workspace_dir}"
    agents_file = candidate / "AGENTS.md"
    if agents_file.is_symlink() or not agents_file.is_file():
        return None, "workspace_dir must contain a regular AGENTS.md at its root"
    try:
        agents_text = agents_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, "workspace_dir/AGENTS.md must be readable UTF-8 text"
    if not agents_text.strip():
        return None, "workspace_dir/AGENTS.md must contain non-blank text"
    return candidate, None


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
    ensure_directory_agents_file(slots_dir)

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
        ensure_directory_agents_file(slot_dir)
        child_workspace_dir.mkdir(parents=True, exist_ok=False)
        copy_seed_workspace(source_workspace_dir, child_workspace_dir)
        ensure_directory_tree_agents_files(child_workspace_dir)
        copied_agents = child_workspace_dir / "AGENTS.md"
        if copied_agents.is_symlink() or not copied_agents.is_file():
            raise RuntimeError("copied child workspace is missing a regular AGENTS.md")
        try:
            copied_agents_text = copied_agents.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("copied child AGENTS.md is not readable UTF-8 text") from exc
        if not copied_agents_text.strip():
            raise RuntimeError("copied child AGENTS.md contains no non-blank text")
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
                **shared_archives_metadata(
                    Path(str(context["shared_archives_root"]))
                ),
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

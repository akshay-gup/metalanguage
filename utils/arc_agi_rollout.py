"""Private per-rollout state for one official ARC environment instance."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from utils.arc_agi_client import ArcAgiClient, ArcAgiClientError
from utils.arc_agi_frames import MAX_SCALE, write_arc_observation_artifacts


SCHEMA_NAME = "metalanguage.arc_rollout_session"
SCHEMA_VERSION = 1
_STATE_FIELDS = {
    "schema",
    "version",
    "base_url",
    "game_id",
    "card_id",
    "guid",
    "artifact_root",
    "render_scale",
    "step_index",
    "operation",
    "state",
    "levels_completed",
    "win_levels",
    "available_actions",
    "latest_manifest_path",
    "latest_frame_paths",
    "latest_hashes",
    "closed",
}


class ArcAgiRolloutError(RuntimeError):
    """Raised for invalid state or failed rollout operations."""


def initialize_arc_rollout(
    state_path: str | Path,
    rollout_root: str | Path,
    base_url: str,
    game_id: str,
    *,
    scale: int = 4,
) -> dict[str, Any]:
    """Open, reset, render, and atomically record a new rollout session."""

    state_file = Path(state_path).resolve()
    artifact_root = (Path(rollout_root).resolve() / "arc_observations")
    _prepare_private_directory(state_file.parent)
    with _state_lock(state_file, exclusive=True):
        if state_file.exists():
            raise ArcAgiRolloutError("ARC rollout state already exists")
        if not isinstance(game_id, str) or not game_id:
            raise ValueError("game_id must be a non-empty string")
        if isinstance(scale, bool) or not isinstance(scale, int) or not 1 <= scale <= MAX_SCALE:
            raise ValueError(f"scale must be an integer from 1 through {MAX_SCALE}")

        client = ArcAgiClient(base_url)
        card_id: str | None = None
        try:
            card_id = client.open_scorecard(tags=["agent", "rollout"])
            response = client.start_game(card_id, game_id)
            artifacts = write_arc_observation_artifacts(
                response, artifact_root, 0, "reset", scale
            )
            metadata = artifacts["metadata"]
            state = {
                "schema": SCHEMA_NAME,
                "version": SCHEMA_VERSION,
                "base_url": client.base_url,
                "game_id": game_id,
                "card_id": card_id,
                "guid": metadata["guid"],
                "artifact_root": str(artifact_root),
                "render_scale": scale,
                "step_index": 0,
                "operation": "reset",
                "state": metadata["state"],
                "levels_completed": metadata["levels_completed"],
                "win_levels": metadata["win_levels"],
                "available_actions": metadata["available_actions"],
                "latest_manifest_path": artifacts["manifest_path"],
                "latest_frame_paths": artifacts["frame_paths"],
                "latest_hashes": _manifest_hashes(metadata),
                "closed": False,
            }
            _validate_state(state)
            _write_state(state_file, state)
            return _model_view(state)
        except ArcAgiClientError:
            if card_id is not None:
                try:
                    client.close_scorecard(card_id)
                except ArcAgiClientError:
                    pass
            raise ArcAgiRolloutError("ARC rollout initialization failed") from None
        except Exception:
            if card_id is not None:
                try:
                    client.close_scorecard(card_id)
                except ArcAgiClientError:
                    pass
            raise


def observe_arc_rollout(state_path: str | Path) -> dict[str, Any]:
    """Return compact latest observation metadata without changing the game."""

    state_file = Path(state_path).resolve()
    with _state_lock(state_file, exclusive=False):
        state = _load_state(state_file)
        _require_open(state)
        _require_artifacts(state)
        return _model_view(state)


def step_arc_rollout(
    state_path: str | Path,
    action: str | int,
    *,
    x: int | None = None,
    y: int | None = None,
    reasoning: Any = None,
) -> dict[str, Any]:
    """Take one currently available action and atomically advance state."""

    state_file = Path(state_path).resolve()
    with _state_lock(state_file, exclusive=True):
        state = _load_state(state_file)
        _require_open(state)
        action_id, action_name = _normalize_step_action(action)
        if action_id not in state["available_actions"]:
            raise ArcAgiRolloutError("action is not available in the latest observation")
        client = ArcAgiClient(state["base_url"])
        try:
            response = client.step(
                state["game_id"],
                state["guid"],
                action_name,
                x=x,
                y=y,
                reasoning=reasoning,
            )
        except ArcAgiClientError:
            raise ArcAgiRolloutError("ARC rollout step failed") from None
        return _record_observation(
            state_file, state, response, action_name.lower()
        )


def reset_arc_rollout(
    state_path: str | Path,
    *,
    reasoning: Any = None,
) -> dict[str, Any]:
    """Reset the existing GUID and atomically record the new observation."""

    state_file = Path(state_path).resolve()
    with _state_lock(state_file, exclusive=True):
        state = _load_state(state_file)
        _require_open(state)
        client = ArcAgiClient(state["base_url"])
        try:
            response = client.reset(
                state["card_id"],
                state["game_id"],
                guid=state["guid"],
                reasoning=reasoning,
            )
        except ArcAgiClientError:
            raise ArcAgiRolloutError("ARC rollout reset failed") from None
        return _record_observation(state_file, state, response, "reset")


def close_arc_rollout(state_path: str | Path) -> dict[str, Any]:
    """Close the scorecard and mark the rollout closed; repeated calls are safe."""

    state_file = Path(state_path).resolve()
    with _state_lock(state_file, exclusive=True):
        state = _load_state(state_file)
        if state["closed"]:
            return _model_view(state)
        client = ArcAgiClient(state["base_url"])
        try:
            client.close_scorecard(state["card_id"])
        except ArcAgiClientError:
            raise ArcAgiRolloutError("ARC rollout close failed") from None
        state["closed"] = True
        _write_state(state_file, state)
        return _model_view(state)


def _record_observation(
    state_file: Path,
    state: dict[str, Any],
    response: dict[str, Any],
    operation: str,
) -> dict[str, Any]:
    if response.get("game_id") != state["game_id"] or response.get("guid") != state["guid"]:
        raise ArcAgiRolloutError("ARC server returned a mismatched environment")
    next_step = state["step_index"] + 1
    artifacts = write_arc_observation_artifacts(
        response,
        state["artifact_root"],
        next_step,
        operation,
        state["render_scale"],
    )
    metadata = artifacts["metadata"]
    state.update(
        step_index=next_step,
        operation=operation,
        state=metadata["state"],
        levels_completed=metadata["levels_completed"],
        win_levels=metadata["win_levels"],
        available_actions=metadata["available_actions"],
        latest_manifest_path=artifacts["manifest_path"],
        latest_frame_paths=artifacts["frame_paths"],
        latest_hashes=_manifest_hashes(metadata),
    )
    _validate_state(state)
    _write_state(state_file, state)
    return _model_view(state)


def _model_view(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "game_id": state["game_id"],
        "state": state["state"],
        "levels_completed": state["levels_completed"],
        "win_levels": state["win_levels"],
        "available_actions": list(state["available_actions"]),
        "step_index": state["step_index"],
        "operation": state["operation"],
        "manifest_path": state["latest_manifest_path"],
        "frame_paths": list(state["latest_frame_paths"]),
        "hashes": state["latest_hashes"],
        "closed": state["closed"],
    }


def _manifest_hashes(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "frame_sequence_sha256": manifest["frame_sequence_sha256"],
        "frames": [
            {
                "grid_sha256": frame["grid_sha256"],
                "png_sha256": frame["png_sha256"],
            }
            for frame in manifest["frames"]
        ],
    }


def _normalize_step_action(action: str | int) -> tuple[int, str]:
    if isinstance(action, bool):
        raise ValueError("action must be ACTION1 through ACTION7")
    if isinstance(action, int):
        action_id = action
    elif isinstance(action, str) and action.upper().startswith("ACTION"):
        suffix = action.upper().removeprefix("ACTION")
        action_id = int(suffix) if suffix.isdigit() else -1
    else:
        action_id = -1
    if not 1 <= action_id <= 7:
        raise ValueError("action must be ACTION1 through ACTION7")
    return action_id, f"ACTION{action_id}"


def _validate_state(state: Any) -> None:
    if not isinstance(state, dict):
        raise ArcAgiRolloutError("ARC rollout state must be a JSON object")
    if state.get("schema") != SCHEMA_NAME or state.get("version") != SCHEMA_VERSION:
        raise ArcAgiRolloutError("unsupported ARC rollout state schema")
    if set(state) != _STATE_FIELDS:
        raise ArcAgiRolloutError("ARC rollout state has unexpected fields")
    for name in (
        "base_url",
        "game_id",
        "card_id",
        "guid",
        "artifact_root",
        "operation",
        "state",
        "latest_manifest_path",
    ):
        if not isinstance(state.get(name), str) or not state[name]:
            raise ArcAgiRolloutError(f"ARC rollout state has invalid {name}")
    try:
        canonical_url = ArcAgiClient(state["base_url"]).base_url
    except ValueError:
        raise ArcAgiRolloutError("ARC rollout state has invalid base_url") from None
    if canonical_url != state["base_url"]:
        raise ArcAgiRolloutError("ARC rollout state has noncanonical base_url")
    for name in ("render_scale", "step_index", "levels_completed", "win_levels"):
        if isinstance(state.get(name), bool) or not isinstance(state.get(name), int):
            raise ArcAgiRolloutError(f"ARC rollout state has invalid {name}")
    if not 1 <= state["render_scale"] <= MAX_SCALE or state["step_index"] < 0:
        raise ArcAgiRolloutError("ARC rollout state has invalid numeric bounds")
    if not 0 <= state["levels_completed"] <= 254 or not 0 <= state["win_levels"] <= 254:
        raise ArcAgiRolloutError("ARC rollout state has invalid progress")
    actions = state.get("available_actions")
    if not isinstance(actions, list) or not all(
        isinstance(action, int) and not isinstance(action, bool) and 0 <= action <= 7
        for action in actions
    ):
        raise ArcAgiRolloutError("ARC rollout state has invalid available_actions")
    if not isinstance(state.get("closed"), bool):
        raise ArcAgiRolloutError("ARC rollout state has invalid closed status")
    if not isinstance(state.get("latest_frame_paths"), list) or not state["latest_frame_paths"]:
        raise ArcAgiRolloutError("ARC rollout state has invalid frame paths")
    _validate_hashes(state.get("latest_hashes"), len(state["latest_frame_paths"]))

    artifact_root = Path(state["artifact_root"])
    if (
        not artifact_root.is_absolute()
        or artifact_root != Path(os.path.normpath(artifact_root))
    ):
        raise ArcAgiRolloutError("ARC rollout artifact root must be absolute")
    paths = [state["latest_manifest_path"], *state["latest_frame_paths"]]
    for value in paths:
        if not isinstance(value, str):
            raise ArcAgiRolloutError("ARC rollout state has invalid artifact path")
        path = Path(value)
        if (
            not path.is_absolute()
            or path != Path(os.path.normpath(path))
            or not path.is_relative_to(artifact_root)
        ):
            raise ArcAgiRolloutError("ARC rollout artifact path escapes artifact root")


def _validate_hashes(value: Any, frame_count: int) -> None:
    if not isinstance(value, dict) or set(value) != {
        "frame_sequence_sha256",
        "frames",
    }:
        raise ArcAgiRolloutError("ARC rollout state has invalid hashes")
    frames = value["frames"]
    if not isinstance(frames, list) or len(frames) != frame_count:
        raise ArcAgiRolloutError("ARC rollout state has invalid frame hashes")
    hashes = [value["frame_sequence_sha256"]]
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) != {"grid_sha256", "png_sha256"}:
            raise ArcAgiRolloutError("ARC rollout state has invalid frame hashes")
        hashes.extend((frame["grid_sha256"], frame["png_sha256"]))
    if not all(
        isinstance(item, str)
        and len(item) == 64
        and all(character in "0123456789abcdef" for character in item)
        for item in hashes
    ):
        raise ArcAgiRolloutError("ARC rollout state has invalid hash value")


def _require_open(state: dict[str, Any]) -> None:
    if state["closed"]:
        raise ArcAgiRolloutError("ARC rollout session is closed")


def _require_artifacts(state: dict[str, Any]) -> None:
    artifact_root = Path(state["artifact_root"]).resolve()
    paths = [state["latest_manifest_path"], *state["latest_frame_paths"]]
    if any(
        not (path := Path(value)).is_file()
        or not path.resolve().is_relative_to(artifact_root)
        for value in paths
    ):
        raise ArcAgiRolloutError(
            "latest ARC observation artifacts are missing or unavailable"
        )


def _load_state(state_file: Path) -> dict[str, Any]:
    try:
        if state_file.stat().st_size > 64 * 1024:
            raise ArcAgiRolloutError("ARC rollout state is too large")
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ArcAgiRolloutError("ARC rollout state does not exist") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ArcAgiRolloutError("ARC rollout state is unreadable") from None
    _validate_state(state)
    return state


def _write_state(state_file: Path, state: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{state_file.name}.", suffix=".tmp", dir=state_file.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, state_file)
        os.chmod(state_file, 0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _prepare_private_directory(directory: Path) -> None:
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)


@contextmanager
def _state_lock(state_file: Path, *, exclusive: bool) -> Iterator[None]:
    if not state_file.parent.is_dir():
        raise ArcAgiRolloutError("ARC rollout state directory does not exist")
    lock_path = state_file.with_name(f"{state_file.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)

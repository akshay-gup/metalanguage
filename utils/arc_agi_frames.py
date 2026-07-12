"""Validate and render ARC observation frames as compact artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image
from arc_agi.rendering import COLOR_MAP, hex_to_rgb


FORMAT_NAME = "arc-agi-observation-artifacts"
FORMAT_VERSION = 2
FRAME_SIZE = 64
MAX_SCALE = 16
_OPERATION_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
_PALETTE = tuple(hex_to_rgb(COLOR_MAP[index]) for index in range(16))


def public_arc_observation(response: dict[str, Any]) -> dict[str, Any]:
    """Validate and copy the official model-visible observation fields."""

    metadata, frames = _validate_response(response)
    action_input = metadata["action_input"]
    return {
        "game_id": metadata["game_id"],
        "frame": [[list(row) for row in frame] for frame in frames],
        "state": metadata["state"],
        "levels_completed": metadata["levels_completed"],
        "win_levels": metadata["win_levels"],
        "available_actions": list(metadata["available_actions"]),
        "action_input": {
            "id": action_input["id"],
            "data": dict(action_input["data"]),
        },
    }


def write_arc_observation_artifacts(
    response: dict[str, Any],
    output_root: str | Path,
    step_index: int,
    operation: str,
    scale: int = 4,
) -> dict[str, Any]:
    """Write one validated ARC observation as ordered PNGs and a manifest."""

    metadata, frames = _validate_response(response)
    if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 0:
        raise ValueError("step_index must be a non-negative integer")
    if isinstance(scale, bool) or not isinstance(scale, int) or not 1 <= scale <= MAX_SCALE:
        raise ValueError(f"scale must be an integer from 1 through {MAX_SCALE}")
    if not isinstance(operation, str):
        raise ValueError("operation must be a short filesystem-safe string")
    operation_name = operation.strip().lower()
    if not _OPERATION_PATTERN.fullmatch(operation_name):
        raise ValueError("operation must be a short filesystem-safe string")

    output_dir = Path(output_root) / f"step_{step_index:06d}_{operation_name}"
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(exist_ok=False)

    rendered_size = FRAME_SIZE * scale
    frame_entries: list[dict[str, Any]] = []
    frame_paths: list[Path] = []
    sequence_hasher = hashlib.sha256()
    for index, frame in enumerate(frames):
        raw_pixels = bytes(cell for row in frame for cell in row)
        sequence_hasher.update(raw_pixels)
        image = Image.new("RGB", (FRAME_SIZE, FRAME_SIZE))
        image.putdata([_PALETTE[cell] for cell in raw_pixels])
        if scale != 1:
            image = image.resize(
                (rendered_size, rendered_size), Image.Resampling.NEAREST
            )
        frame_name = f"frame_{index:03d}.png"
        frame_path = output_dir / frame_name
        image.save(frame_path, format="PNG")
        frame_paths.append(frame_path)
        frame_entries.append(
            {
                "index": index,
                "path": frame_name,
                "grid_sha256": hashlib.sha256(raw_pixels).hexdigest(),
                "png_sha256": hashlib.sha256(frame_path.read_bytes()).hexdigest(),
            }
        )

    public_metadata = {
        key: value for key, value in metadata.items() if key != "guid"
    }
    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        **public_metadata,
        "frame_semantics": "ordered sequential frames from one ARC observation",
        "frame_count": len(frames),
        "dimensions": {
            "original": {"width": FRAME_SIZE, "height": FRAME_SIZE},
            "rendered": {"width": rendered_size, "height": rendered_size},
            "scale": scale,
        },
        "frame_sequence_sha256": sequence_hasher.hexdigest(),
        "frames": frame_entries,
    }
    manifest_path = output_dir / "observation.json"
    temporary_manifest = output_dir / ".observation.json.tmp"
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary_manifest.replace(manifest_path)

    return {
        "directory": str(output_dir),
        "manifest_path": str(manifest_path),
        "frame_paths": [str(path) for path in frame_paths],
        "metadata": manifest,
    }


def _validate_response(
    response: dict[str, Any],
) -> tuple[dict[str, Any], Sequence[Sequence[Sequence[int]]]]:
    if not isinstance(response, dict):
        raise ValueError("response must be a JSON object")
    frames = response.get("frame")
    if not _is_sequence(frames) or not frames:
        raise ValueError("frame must be a non-empty sequence")
    for frame_index, frame in enumerate(frames):
        if not _is_sequence(frame) or len(frame) != FRAME_SIZE:
            raise ValueError(f"frame {frame_index} must have exactly 64 rows")
        for row_index, row in enumerate(frame):
            if not _is_sequence(row) or len(row) != FRAME_SIZE:
                raise ValueError(
                    f"frame {frame_index} row {row_index} must have exactly 64 cells"
                )
            for cell in row:
                if isinstance(cell, bool) or not isinstance(cell, int) or not 0 <= cell <= 15:
                    raise ValueError("frame cells must be integers from 0 through 15")

    game_id = _require_string(response, "game_id")
    guid = _require_string(response, "guid")
    state = _require_string(response, "state")
    levels_completed = _require_count(response, "levels_completed")
    win_levels = _require_count(response, "win_levels")
    available_actions = response.get("available_actions")
    if not isinstance(available_actions, list) or not all(
        isinstance(action, int) and not isinstance(action, bool) and 0 <= action <= 7
        for action in available_actions
    ):
        raise ValueError("available_actions must contain action IDs from 0 through 7")
    action_input = _compact_action_input(response.get("action_input"))
    return (
        {
            "game_id": game_id,
            "guid": guid,
            "state": state,
            "levels_completed": levels_completed,
            "win_levels": win_levels,
            "available_actions": available_actions,
            "action_input": action_input,
        },
        frames,
    )


def _compact_action_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("action_input must be a JSON object")
    action_id = value.get("id")
    if isinstance(action_id, bool) or not isinstance(action_id, int) or not 0 <= action_id <= 7:
        raise ValueError("action_input.id must be an action ID from 0 through 7")
    data = value.get("data")
    if not isinstance(data, dict):
        raise ValueError("action_input.data must be a JSON object")
    compact_data: dict[str, Any] = {}
    if "game_id" in data:
        if not isinstance(data["game_id"], str):
            raise ValueError("action_input.data.game_id must be a string")
        compact_data["game_id"] = data["game_id"]
    for coordinate in ("x", "y"):
        if coordinate in data:
            coordinate_value = data[coordinate]
            if (
                isinstance(coordinate_value, bool)
                or not isinstance(coordinate_value, int)
                or not 0 <= coordinate_value <= 63
            ):
                raise ValueError(f"action_input.data.{coordinate} must be in 0..63")
            compact_data[coordinate] = coordinate_value
    return {
        "id": action_id,
        "data": compact_data,
        "reasoning_present": value.get("reasoning") is not None,
    }


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _require_string(response: dict[str, Any], name: str) -> str:
    value = response.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_count(response: dict[str, Any], name: str) -> int:
    value = response.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 254:
        raise ValueError(f"{name} must be an integer from 0 through 254")
    return value

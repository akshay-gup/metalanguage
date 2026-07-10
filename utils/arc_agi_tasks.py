"""ARC-AGI task-pool helpers.

This module converts ARC-AGI environment metadata into Metalanguage-like pool
records. It does not wire ARC into the main rollout loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.arc_agi_env import _jsonable, make_arcade


def arc_task_uuid(game_id: str) -> str:
    """Return a stable Metalanguage-style uid for one ARC environment id."""

    digest = hashlib.sha256(game_id.encode("utf-8")).hexdigest()[:16]
    safe = "".join(ch if ch.isalnum() else "_" for ch in game_id.lower()).strip("_")
    safe = safe[:48] or "game"
    return f"arc_agi_3_{safe}_{digest}"


def environment_info_records(arcade: Any | None = None) -> list[dict[str, Any]]:
    """Fetch available ARC environments and normalize them as task records."""

    if arcade is None:
        arcade = make_arcade()

    environments = getattr(arcade, "available_environments", None)
    if environments is None:
        get_environments = getattr(arcade, "get_environments", None)
        environments = get_environments() if callable(get_environments) else []

    records: list[dict[str, Any]] = []
    for info in environments or []:
        payload = _jsonable(info)
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        game_id = str(payload.get("game_id") or payload.get("id") or "").strip()
        if not game_id:
            continue
        records.append(
            {
                "uuid": arc_task_uuid(game_id),
                "task_source": "arc_agi_3",
                "task_type": "interactive_environment",
                "game_id": game_id,
                "title": payload.get("title"),
                "tags": payload.get("tags") or [],
                "level_tags": payload.get("level_tags"),
                "default_fps": payload.get("default_fps"),
                "baseline_actions": payload.get("baseline_actions"),
                "class_name": payload.get("class_name"),
                "metadata": payload,
            }
        )
    return sorted(records, key=lambda item: item["game_id"])


def write_arc_task_pool(
    *,
    json_path: Path,
    markdown_path: Path,
    records: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path]:
    """Write ARC environment records as JSON and a human-readable Markdown pool."""

    if records is None:
        records = environment_info_records()

    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# ARC-AGI-3 Environment Pool",
        "",
        "Choose an environment by uuid/game_id. This is an interactive environment pool, not a static answer dataset.",
        "",
        f"Total environments: {len(records)}",
        "",
    ]
    for index, record in enumerate(records, start=1):
        tags = ", ".join(str(tag) for tag in record.get("tags") or []) or "none"
        baselines = record.get("baseline_actions")
        baseline_text = ", ".join(str(item) for item in baselines) if isinstance(baselines, list) else "unknown"
        lines.extend(
            [
                f"## {index}. {record.get('title') or record['game_id']}",
                "",
                f"- uuid: `{record['uuid']}`",
                f"- game_id: `{record['game_id']}`",
                f"- tags: {tags}",
                f"- default_fps: {record.get('default_fps')}",
                f"- baseline_actions_by_level: {baseline_text}",
                "",
            ]
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path.resolve(), markdown_path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ARC-AGI task-pool files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Print normalized ARC environment records as JSON.")

    write_parser = subparsers.add_parser("write-pool", help="Write ARC pool JSON and Markdown files.")
    write_parser.add_argument("--json-path", required=True)
    write_parser.add_argument("--markdown-path", required=True)

    args = parser.parse_args()
    records = environment_info_records()
    if args.command == "list":
        print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "write-pool":
        json_path, markdown_path = write_arc_task_pool(
            json_path=Path(args.json_path),
            markdown_path=Path(args.markdown_path),
            records=records,
        )
        print(json.dumps({"count": len(records), "json_path": str(json_path), "markdown_path": str(markdown_path)}))
        return
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    main()

"""ARC-AGI reusable public-environment catalog helpers.

This module converts ARC-AGI environment metadata into catalog records. Public
environments remain reusable regardless of previously observed WIN states; an
optional deterministic sampling cap may select a smaller per-iteration catalog.
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
from utils.problem_pool_sampling import deterministic_problem_pool_sample


def arc_task_uuid(game_id: str) -> str:
    """Return a stable compatibility uid for one ARC environment id."""

    digest = hashlib.sha256(game_id.encode("utf-8")).hexdigest()[:16]
    safe = "".join(ch if ch.isalnum() else "_" for ch in game_id.lower()).strip("_")
    safe = safe[:48] or "game"
    return f"arc_agi_3_{safe}_{digest}"


def environment_info_records(arcade: Any | None = None) -> list[dict[str, Any]]:
    """Fetch available ARC environments and normalize them as catalog records."""

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
        # Remote listings stamp fetch time into this field, which is not task
        # identity and would make identical sampled pools differ across runs.
        payload.pop("date_downloaded", None)
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
    configured_problem_pool_size: int | None = None,
    seed: int = 42,
    iteration_index: int = 0,
) -> tuple[Path, Path]:
    """Write ARC environment records as a reusable public catalog."""

    if records is None:
        records = environment_info_records()

    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    capped = configured_problem_pool_size is not None
    lines = [
        "# ARC-AGI-3 Reusable Public Environment Catalog",
        "",
        "Records are keyed by uuid/game_id. These are reusable interactive practice/evaluation environments, not individual human tasks or a static answer dataset.",
        "",
        "A prior WIN is diagnostic history and does not remove an environment from later catalogs.",
        "",
        (
            "This is a deterministic sampled catalog, not necessarily the full public environment universe."
            if capped
            else "This catalog contains every environment record supplied by the caller."
        ),
        "",
        f"Configured environment-catalog sampling cap: {configured_problem_pool_size if capped else 'uncapped'}",
        "",
        f"Catalog record count: {len(records)}",
        "",
        f"Sampling seed: {seed}",
        "",
        f"Iteration index: {iteration_index}",
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


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _add_sampling_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--problem-pool-size",
        type=_positive_int,
        default=None,
        help="Maximum number of environment records to include. Defaults to uncapped.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed.")
    parser.add_argument(
        "--iteration-index",
        type=int,
        default=0,
        help="Iteration index mixed into deterministic sampling.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ARC-AGI public environment catalog files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Print normalized ARC environment records as JSON.")
    _add_sampling_arguments(list_parser)

    write_parser = subparsers.add_parser(
        "write-pool",
        help="Write ARC catalog JSON and Markdown files (compatibility command name).",
    )
    write_parser.add_argument("--json-path", required=True)
    write_parser.add_argument("--markdown-path", required=True)
    _add_sampling_arguments(write_parser)

    args = parser.parse_args()
    candidate_records = environment_info_records()
    records = deterministic_problem_pool_sample(
        candidate_records,
        problem_pool_size=args.problem_pool_size,
        seed=args.seed,
        iteration_index=args.iteration_index,
        record_id=lambda record: str(record["uuid"]),
    )
    if args.command == "list":
        print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "write-pool":
        json_path, markdown_path = write_arc_task_pool(
            json_path=Path(args.json_path),
            markdown_path=Path(args.markdown_path),
            records=records,
            configured_problem_pool_size=args.problem_pool_size,
            seed=args.seed,
            iteration_index=args.iteration_index,
        )
        print(
            json.dumps(
                {
                    "configured_problem_pool_size": args.problem_pool_size,
                    "count": len(records),
                    "iteration_index": args.iteration_index,
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                    "seed": args.seed,
                }
            )
        )
        return
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    main()

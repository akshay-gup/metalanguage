"""Optional ARC-AGI environment adapter.

This module is intentionally isolated from the main rollout loop. It lets us
probe and normalize the ARC-AGI toolkit before wiring it into Metalanguage task
generation or scoring.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


DEFAULT_ARC_API_KEY_ENV = "ARC_API_KEY"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


class ArcAgiUnavailable(RuntimeError):
    """Raised when the optional ARC-AGI toolkit is not installed/configured."""


@dataclass(frozen=True)
class ArcAgiModules:
    arc_agi: Any
    arcengine: Any | None


@dataclass
class ArcAgiSession:
    """A live ARC-AGI game environment plus its owning Arcade client."""

    game_id: str
    arcade: Any
    env: Any
    render_mode: str | None = None

    def step(self, action: Any) -> dict[str, Any]:
        resolved_action = resolve_action(action, self.arcengine_module)
        raw = self.env.step(resolved_action)
        return {
            "game_id": self.game_id,
            "action": action,
            "resolved_action": _jsonable(resolved_action),
            "observation": _jsonable(raw),
            "scorecard": get_scorecard(self.arcade),
        }

    @property
    def arcengine_module(self) -> Any | None:
        return getattr(self.arcade, "__metalanguage_arcengine_module__", None)


def load_env_file(env_path: Path = DEFAULT_ENV_PATH) -> None:
    """Load simple KEY=VALUE entries without overriding real environment values."""

    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def dependency_status(*, api_key_env: str = DEFAULT_ARC_API_KEY_ENV) -> dict[str, Any]:
    """Return import/API-key status without creating an environment."""

    load_env_file()
    status: dict[str, Any] = {
        "arc_agi_installed": importlib.util.find_spec("arc_agi") is not None,
        "arcengine_installed": importlib.util.find_spec("arcengine") is not None,
        "api_key_env": api_key_env,
        "api_key_present": bool(os.environ.get(api_key_env)),
    }
    if not status["arc_agi_installed"]:
        status["install_hint"] = "Install the optional ARC toolkit, e.g. `uv add arc-agi`."
    return status


def load_arc_agi_modules() -> ArcAgiModules:
    """Import optional ARC-AGI modules, raising a clear local error on failure."""

    try:
        arc_agi = importlib.import_module("arc_agi")
    except ImportError as exc:
        raise ArcAgiUnavailable(
            "ARC-AGI toolkit is not installed. Install it before using this adapter."
        ) from exc

    try:
        arcengine = importlib.import_module("arcengine")
    except ImportError:
        arcengine = None

    return ArcAgiModules(arc_agi=arc_agi, arcengine=arcengine)


def make_arcade(*, api_key_env: str = DEFAULT_ARC_API_KEY_ENV) -> Any:
    """Construct an ARC Arcade client using the toolkit's current defaults."""

    load_env_file()
    modules = load_arc_agi_modules()
    if not os.environ.get(api_key_env):
        raise ArcAgiUnavailable(f"{api_key_env} is not set.")

    arcade_factory = getattr(modules.arc_agi, "Arcade", None)
    if arcade_factory is None:
        raise ArcAgiUnavailable("arc_agi.Arcade was not found in the installed toolkit.")

    arcade = arcade_factory()
    setattr(arcade, "__metalanguage_arcengine_module__", modules.arcengine)
    return arcade


def list_games(arcade: Any) -> list[str]:
    """Best-effort game listing across possible toolkit API shapes."""

    candidates = (
        "list_games",
        "games",
        "available_games",
        "game_ids",
        "catalog",
    )
    for name in candidates:
        value = getattr(arcade, name, None)
        if value is None:
            continue
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
        games = _coerce_game_list(value)
        if games:
            return games
    return []


def start_game(
    game_id: str,
    *,
    render_mode: str | None = "terminal",
    api_key_env: str = DEFAULT_ARC_API_KEY_ENV,
) -> ArcAgiSession:
    """Create a live ARC game session."""

    if not game_id or not str(game_id).strip():
        raise ValueError("game_id must be non-empty")

    arcade = make_arcade(api_key_env=api_key_env)
    make = getattr(arcade, "make", None)
    if not callable(make):
        raise ArcAgiUnavailable("Arcade.make(game_id, ...) was not found.")

    kwargs = {"render_mode": render_mode} if render_mode else {}
    env = make(str(game_id), **kwargs)
    return ArcAgiSession(game_id=str(game_id), arcade=arcade, env=env, render_mode=render_mode)


def resolve_action(action: Any, arcengine: Any | None) -> Any:
    """Resolve string action names to arcengine.GameAction enum values when possible."""

    if isinstance(action, str) and arcengine is not None:
        game_action = getattr(arcengine, "GameAction", None)
        if game_action is not None:
            normalized = action.strip()
            for candidate in (normalized, normalized.upper(), normalized.lower()):
                if hasattr(game_action, candidate):
                    return getattr(game_action, candidate)
    return action


def available_actions(arcengine: Any | None = None) -> list[str]:
    """Return known GameAction names if arcengine is available."""

    if arcengine is None:
        try:
            arcengine = load_arc_agi_modules().arcengine
        except ArcAgiUnavailable:
            return []
    game_action = getattr(arcengine, "GameAction", None) if arcengine is not None else None
    if game_action is None:
        return []
    if isinstance(game_action, type) and issubclass(game_action, Enum):
        return [member.name for member in game_action]
    return [
        name
        for name in dir(game_action)
        if name.isupper() and not name.startswith("_")
    ]


def get_scorecard(arcade: Any) -> Any:
    """Return the toolkit scorecard if the current Arcade client exposes one."""

    get_scorecard_fn = getattr(arcade, "get_scorecard", None)
    if not callable(get_scorecard_fn):
        return None
    try:
        return _jsonable(get_scorecard_fn())
    except Exception as exc:  # pragma: no cover - depends on external toolkit state.
        return {"error": f"{type(exc).__name__}: {exc}"}


def _coerce_game_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(key) for key in value.keys()]
    if isinstance(value, (str, bytes)):
        return [value.decode() if isinstance(value, bytes) else value]
    if isinstance(value, list | tuple | set):
        games: list[str] = []
        for item in value:
            if isinstance(item, dict):
                game_id = item.get("id") or item.get("game_id") or item.get("name")
                if game_id is not None:
                    games.append(str(game_id))
            else:
                games.append(str(item))
        return games
    return []


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return repr(value)


def _print_json(payload: Any) -> None:
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the optional ARC-AGI toolkit adapter.")
    parser.add_argument("--api-key-env", default=DEFAULT_ARC_API_KEY_ENV)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check dependency and API-key status.")
    subparsers.add_parser("actions", help="List known arcengine.GameAction names.")
    subparsers.add_parser("list-games", help="Best-effort list of available games.")

    start_parser = subparsers.add_parser("start", help="Start one game and print initial metadata.")
    start_parser.add_argument("game_id")
    start_parser.add_argument("--render-mode", default="terminal")

    step_parser = subparsers.add_parser("step", help="Start one game and run one action.")
    step_parser.add_argument("game_id")
    step_parser.add_argument("action")
    step_parser.add_argument("--render-mode", default="terminal")

    args = parser.parse_args()
    if args.command == "doctor":
        _print_json(dependency_status(api_key_env=args.api_key_env))
        return
    if args.command == "actions":
        _print_json(available_actions())
        return
    if args.command == "list-games":
        _print_json(list_games(make_arcade(api_key_env=args.api_key_env)))
        return
    if args.command == "start":
        session = start_game(
            args.game_id,
            render_mode=args.render_mode,
            api_key_env=args.api_key_env,
        )
        _print_json(
            {
                "game_id": session.game_id,
                "render_mode": session.render_mode,
                "actions": available_actions(session.arcengine_module),
                "scorecard": get_scorecard(session.arcade),
            }
        )
        return
    if args.command == "step":
        session = start_game(
            args.game_id,
            render_mode=args.render_mode,
            api_key_env=args.api_key_env,
        )
        _print_json(session.step(args.action))
        return
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    main()

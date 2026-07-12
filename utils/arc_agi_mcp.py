"""Per-rollout stdio MCP surface for official ARC-AGI commands.

The official HTTP command, artifact render, and local atomic state replacement
cannot form one transaction. A process crash between them can leave local state
behind the server; this transport intentionally adds no retry protocol.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import Field, StrictInt

from utils.arc_agi_client import ArcAgiClient
from utils.arc_agi_frames import MAX_SCALE
from utils.arc_agi_rollout import (
    ArcAgiCommandResult,
    arc_rollout_game_id,
    initialize_arc_rollout_command,
    reset_arc_rollout_command,
    step_arc_rollout_command,
)


CONTEXT_ENV = "METALANGUAGE_ARC_CONTEXT"
CONTEXT_SCHEMA = "metalanguage.arc_mcp_context"
CONTEXT_VERSION = 1
_CONTEXT_FIELDS = {
    "schema",
    "version",
    "allowed_game_ids",
    "base_url",
    "state_root",
    "state_path",
    "rollout_root",
    "artifact_root",
    "render_scale",
}

mcp = FastMCP("ARC-AGI", json_response=True)


class ArcAgiMcpError(RuntimeError):
    """A safe command or private-context failure."""


@dataclass(frozen=True)
class ArcMcpContext:
    allowed_game_ids: tuple[str, ...]
    base_url: str = field(repr=False)
    state_root: Path = field(repr=False)
    state_path: Path = field(repr=False)
    rollout_root: Path = field(repr=False)
    artifact_root: Path = field(repr=False)
    render_scale: int


class ArcCommandService:
    """Route official commands through one reconnectable rollout session."""

    def __init__(
        self,
        context: ArcMcpContext,
        *,
        initialize: Callable[..., ArcAgiCommandResult] = initialize_arc_rollout_command,
        reset: Callable[..., ArcAgiCommandResult] = reset_arc_rollout_command,
        step: Callable[..., ArcAgiCommandResult] = step_arc_rollout_command,
        selected_game: Callable[[str | Path], str] = arc_rollout_game_id,
    ) -> None:
        self.context = context
        self._initialize = initialize
        self._reset = reset
        self._step = step
        self._selected_game = selected_game

    def reset(self, game_id: str) -> ArcAgiCommandResult:
        if not isinstance(game_id, str) or game_id not in self.context.allowed_game_ids:
            raise ArcAgiMcpError("RESET game_id is not in the assigned ARC pool")
        if self.context.state_path.exists():
            try:
                selected = self._selected_game(self.context.state_path)
            except Exception:
                raise ArcAgiMcpError("ARC rollout state is unavailable") from None
            if selected != game_id:
                raise ArcAgiMcpError("RESET cannot change the selected ARC game")
            try:
                return self._reset(self.context.state_path)
            except Exception:
                raise ArcAgiMcpError("ARC RESET failed") from None
        try:
            return self._initialize(
                self.context.state_path,
                self.context.rollout_root,
                self.context.base_url,
                game_id,
                scale=self.context.render_scale,
            )
        except Exception:
            raise ArcAgiMcpError("ARC RESET failed") from None

    def action(
        self,
        action: str,
        *,
        x: int | None = None,
        y: int | None = None,
    ) -> ArcAgiCommandResult:
        if not self.context.state_path.exists():
            raise ArcAgiMcpError("RESET must be called before an ARC action")
        try:
            return self._step(self.context.state_path, action, x=x, y=y)
        except Exception:
            raise ArcAgiMcpError(f"ARC {action} failed") from None


def load_context(path: str | Path) -> ArcMcpContext:
    context_path = _canonical_file(Path(path), "ARC handler context")
    _require_private_file(context_path, "ARC handler context")
    _require_private_directory(context_path.parent, "ARC handler context directory")
    try:
        if context_path.stat().st_size > 64 * 1024:
            raise ArcAgiMcpError("ARC handler context is too large")
        value = json.loads(context_path.read_text(encoding="utf-8"))
    except ArcAgiMcpError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ArcAgiMcpError("ARC handler context is unreadable") from None
    if not isinstance(value, dict) or set(value) != _CONTEXT_FIELDS:
        raise ArcAgiMcpError("ARC handler context has an invalid schema")
    if value.get("schema") != CONTEXT_SCHEMA or value.get("version") != CONTEXT_VERSION:
        raise ArcAgiMcpError("ARC handler context has an unsupported version")

    games = value.get("allowed_game_ids")
    if (
        not isinstance(games, list)
        or not games
        or not all(isinstance(game, str) and game for game in games)
        or len(games) != len(set(games))
    ):
        raise ArcAgiMcpError("ARC handler context has invalid allowed games")
    try:
        base_url = ArcAgiClient(value.get("base_url")).base_url
    except (TypeError, ValueError):
        raise ArcAgiMcpError("ARC handler context has invalid server configuration") from None
    if base_url != value["base_url"]:
        raise ArcAgiMcpError("ARC handler context has noncanonical server configuration")

    state_root = _canonical_directory(value.get("state_root"), "ARC state root")
    rollout_root = _canonical_directory(value.get("rollout_root"), "ARC rollout root")
    _require_private_directory(state_root, "ARC state root")
    _require_private_directory(rollout_root, "ARC rollout root")
    state_path = _canonical_path(value.get("state_path"), "ARC state path")
    artifact_root = _canonical_path(value.get("artifact_root"), "ARC artifact root")
    if state_path.parent != state_root or state_path.name != "arc_session.json":
        raise ArcAgiMcpError("ARC handler context has invalid state containment")
    if artifact_root != rollout_root / "arc_observations":
        raise ArcAgiMcpError("ARC handler context has invalid artifact containment")
    if artifact_root.exists() and (
        artifact_root.is_symlink()
        or not artifact_root.is_dir()
        or artifact_root.resolve() != artifact_root
    ):
        raise ArcAgiMcpError("ARC artifact root is unavailable")
    for private_file, label in (
        (state_path, "ARC state file"),
        (state_path.with_name(f"{state_path.name}.lock"), "ARC state lock"),
    ):
        if private_file.exists():
            _require_private_file(_canonical_file(private_file, label), label)

    scale = value.get("render_scale")
    if isinstance(scale, bool) or not isinstance(scale, int) or not 1 <= scale <= MAX_SCALE:
        raise ArcAgiMcpError("ARC handler context has invalid render scale")
    return ArcMcpContext(
        tuple(games),
        base_url,
        state_root,
        state_path,
        rollout_root,
        artifact_root,
        scale,
    )


def _load_service() -> ArcCommandService:
    raw = os.environ.get(CONTEXT_ENV)
    if not raw:
        raise ArcAgiMcpError("ARC handler context is not configured")
    path = Path(raw)
    if not path.is_absolute():
        raise ArcAgiMcpError("ARC handler context must be absolute")
    return ArcCommandService(load_context(path))


_SERVICE: ArcCommandService | None = None
_PROCESS_LOCK_FD: int | None = None


def _service() -> ArcCommandService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _load_service()
    return _SERVICE


def _result(command: Callable[[], ArcAgiCommandResult]) -> CallToolResult:
    result = command()
    observation = result.observation
    summary = {
        key: observation[key]
        for key in (
            "game_id",
            "state",
            "levels_completed",
            "win_levels",
            "available_actions",
            "action_input",
        )
    }
    summary["frame_count"] = len(observation["frame"])
    content: list[TextContent | ImageContent] = [
        TextContent(type="text", text=json.dumps(summary, separators=(",", ":")))
    ]
    for frame_path in result.frame_paths:
        try:
            encoded = base64.b64encode(frame_path.read_bytes()).decode("ascii")
        except OSError:
            raise ArcAgiMcpError("ARC frame rendering is unavailable") from None
        content.append(
            ImageContent(
                type="image",
                data=encoded,
                mimeType="image/png",
                _meta={"codex/imageDetail": "original"},
            )
        )
    return CallToolResult(content=content, structuredContent=observation)


@mcp.tool(name="RESET")
def RESET(game_id: str) -> CallToolResult:
    """Issue official RESET for one assigned ARC game_id."""

    return _result(lambda: _service().reset(game_id))


def _action(action: str, *, x: int | None = None, y: int | None = None) -> CallToolResult:
    return _result(lambda: _service().action(action, x=x, y=y))


@mcp.tool(name="ACTION1")
def ACTION1() -> CallToolResult:
    """Issue official ARC command ACTION1."""

    return _action("ACTION1")


@mcp.tool(name="ACTION2")
def ACTION2() -> CallToolResult:
    """Issue official ARC command ACTION2."""

    return _action("ACTION2")


@mcp.tool(name="ACTION3")
def ACTION3() -> CallToolResult:
    """Issue official ARC command ACTION3."""

    return _action("ACTION3")


@mcp.tool(name="ACTION4")
def ACTION4() -> CallToolResult:
    """Issue official ARC command ACTION4."""

    return _action("ACTION4")


@mcp.tool(name="ACTION5")
def ACTION5() -> CallToolResult:
    """Issue official ARC command ACTION5."""

    return _action("ACTION5")


@mcp.tool(name="ACTION6")
def ACTION6(
    x: Annotated[StrictInt, Field(ge=0, le=63)],
    y: Annotated[StrictInt, Field(ge=0, le=63)],
) -> CallToolResult:
    """Issue official ARC command ACTION6 at integer coordinates x,y in 0..63."""

    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 63:
        raise ArcAgiMcpError("ACTION6 x must be an integer from 0 through 63")
    if isinstance(y, bool) or not isinstance(y, int) or not 0 <= y <= 63:
        raise ArcAgiMcpError("ACTION6 y must be an integer from 0 through 63")
    return _action("ACTION6", x=x, y=y)


@mcp.tool(name="ACTION7")
def ACTION7() -> CallToolResult:
    """Issue official ARC command ACTION7 (Undo)."""

    return _action("ACTION7")


def _canonical_path(value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise ArcAgiMcpError(f"{label} is invalid")
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise ArcAgiMcpError(f"{label} must be absolute and normalized")
    return path


def _canonical_file(path: Path, label: str) -> Path:
    path = _canonical_path(str(path), label)
    if path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise ArcAgiMcpError(f"{label} is unavailable")
    return path


def _canonical_directory(value: Any, label: str) -> Path:
    path = _canonical_path(value, label)
    if path.is_symlink() or not path.is_dir() or path.resolve() != path:
        raise ArcAgiMcpError(f"{label} is unavailable")
    return path


def _require_owner(path: Path, label: str) -> os.stat_result:
    info = path.stat()
    if info.st_uid != os.geteuid():
        raise ArcAgiMcpError(f"{label} has invalid ownership")
    return info


def _require_private_file(path: Path, label: str) -> None:
    if stat.S_IMODE(_require_owner(path, label).st_mode) != 0o600:
        raise ArcAgiMcpError(f"{label} must have mode 0600")


def _require_private_directory(path: Path, label: str) -> None:
    if stat.S_IMODE(_require_owner(path, label).st_mode) != 0o700:
        raise ArcAgiMcpError(f"{label} must have mode 0700")


def _acquire_process_lock(context_path: Path) -> int:
    lock_path = context_path.with_name(f"{context_path.name}.process.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(descriptor, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise ArcAgiMcpError("ARC rollout already has an active command server") from None
    return descriptor


def main() -> None:
    global _PROCESS_LOCK_FD, _SERVICE
    raw = os.environ.get(CONTEXT_ENV)
    if not raw or not Path(raw).is_absolute():
        raise ArcAgiMcpError("ARC handler context is not configured")
    context_path = Path(raw)
    _SERVICE = ArcCommandService(load_context(context_path))
    _PROCESS_LOCK_FD = _acquire_process_lock(context_path)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

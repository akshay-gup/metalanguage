from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from arc_agi.rendering import COLOR_MAP, hex_to_rgb
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

from utils.arc_agi_mcp import (
    CONTEXT_ENV,
    CONTEXT_SCHEMA,
    CONTEXT_VERSION,
    ArcAgiMcpError,
    _acquire_process_lock,
    load_context,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["RESET", *(f"ACTION{index}" for index in range(1, 8))]


def _grid(color: int) -> list[list[int]]:
    return [[color for _column in range(64)] for _row in range(64)]


class _FakeArcState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_card = 0
        self.commands: list[tuple[str, dict[str, Any]]] = []

    def response(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.commands.append((command, payload))
            action_id = 0 if command == "RESET" else int(command.removeprefix("ACTION"))
            guid = payload.get("guid") or f"private-guid-{payload.get('card_id')}"
            data: dict[str, Any] = {}
            if command == "RESET":
                data["game_id"] = payload["game_id"]
            if command == "ACTION6":
                data.update(x=payload["x"], y=payload["y"])
            frames = [_grid(action_id), _grid((action_id + 1) % 16)] if command == "RESET" else [_grid(action_id)]
            return {
                "game_id": payload["game_id"],
                "guid": guid,
                "frame": frames,
                "state": "NOT_FINISHED",
                "levels_completed": 0,
                "win_levels": 1,
                "available_actions": [1, 6, 7] if command == "RESET" else [6, 7],
                "action_input": {"id": action_id, "data": data, "reasoning": None},
            }


class _FakeArcHandler(BaseHTTPRequestHandler):
    server: _FakeArcServer

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size) or b"{}")
        if self.path == "/api/scorecard/open":
            with self.server.state.lock:
                card_id = f"private-card-{self.server.state.next_card}"
                self.server.state.next_card += 1
            self._send({"card_id": card_id})
            return
        if self.path == "/api/scorecard/close":
            self._send({"card_id": payload.get("card_id")})
            return
        prefix = "/api/cmd/"
        if self.path.startswith(prefix):
            self._send(self.server.state.response(self.path.removeprefix(prefix), payload))
            return
        self.send_error(404)

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def _send(self, value: dict[str, Any]) -> None:
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class _FakeArcServer(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _FakeArcHandler)
        self.state = _FakeArcState()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


def _write_context(
    root: Path,
    name: str,
    base_url: str,
    games: list[str],
    *,
    extra: dict[str, Any] | None = None,
) -> tuple[Path, Path, Path]:
    private = root / name
    control = private / "control"
    state_root = private / "state"
    rollout_root = private / "rollout"
    for directory in (private, control, state_root, rollout_root):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    state_path = state_root / "arc_session.json"
    context_path = control / "arc_context.json"
    payload = {
        "schema": CONTEXT_SCHEMA,
        "version": CONTEXT_VERSION,
        "allowed_game_ids": games,
        "base_url": base_url,
        "state_root": str(state_root),
        "state_path": str(state_path),
        "rollout_root": str(rollout_root),
        "artifact_root": str(rollout_root / "arc_observations"),
        "render_scale": 2,
        **(extra or {}),
    }
    context_path.write_text(json.dumps(payload), encoding="utf-8")
    context_path.chmod(0o600)
    return context_path, state_path, rollout_root


def _parameters(context_path: Path) -> StdioServerParameters:
    env = os.environ.copy()
    env[CONTEXT_ENV] = str(context_path)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "utils.arc_agi_mcp"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )


class ArcAgiMcpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = _FakeArcServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    async def asyncTearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    async def test_official_protocol_commands_images_and_session_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_path, state_path, _rollout = _write_context(
                root, "one", self.server.base_url, ["game-a", "game-b"]
            )
            async with stdio_client(_parameters(context_path)) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.assertEqual([tool.name for tool in listed.tools], TOOLS)
                    schemas = {tool.name: tool.inputSchema for tool in listed.tools}
                    self.assertEqual(set(schemas["RESET"]["properties"]), {"game_id"})
                    for name in ["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION7"]:
                        self.assertEqual(schemas[name]["properties"], {})
                    self.assertEqual(set(schemas["ACTION6"]["properties"]), {"x", "y"})
                    for coordinate in ("x", "y"):
                        self.assertEqual(schemas["ACTION6"]["properties"][coordinate]["minimum"], 0)
                        self.assertEqual(schemas["ACTION6"]["properties"][coordinate]["maximum"], 63)
                    schema_text = json.dumps(schemas, sort_keys=True)
                    self.assertNotIn("reason", schema_text.lower())
                    self.assertNotIn(str(context_path), schema_text)

                    before = await session.call_tool("ACTION1", {})
                    self.assertTrue(before.isError)
                    disallowed = await session.call_tool("RESET", {"game_id": "other"})
                    self.assertTrue(disallowed.isError)

                    reset = await session.call_tool("RESET", {"game_id": "game-a"})
                    self.assertFalse(reset.isError)
                    observation = reset.structuredContent
                    assert isinstance(observation, dict)
                    self.assertEqual(observation["game_id"], "game-a")
                    self.assertEqual(len(observation["frame"]), 2)
                    self.assertEqual(observation["action_input"], {"id": 0, "data": {"game_id": "game-a"}})
                    self.assertEqual([block.type for block in reset.content], ["text", "image", "image"])
                    text_summary = json.loads(reset.content[0].text)
                    self.assertEqual(text_summary["frame_count"], 2)
                    self.assertNotIn("frame", text_summary)
                    self.assertNotIn("guid", json.dumps(observation))
                    self.assertNotIn("card", json.dumps(observation))
                    self.assertNotIn(str(state_path), json.dumps(observation))

                    images = [block for block in reset.content if block.type == "image"]
                    artifact_dir = root / "one/rollout/arc_observations/step_000000_reset"
                    frame_paths = sorted(artifact_dir.glob("frame_*.png"))
                    manifest_text = (artifact_dir / "observation.json").read_text()
                    manifest = json.loads(manifest_text)
                    self.assertEqual(manifest["version"], 2)
                    self.assertNotIn("guid", manifest)
                    self.assertNotIn("private-guid", manifest_text)
                    self.assertEqual(
                        [hashlib.sha256(base64.b64decode(image.data)).hexdigest() for image in images],
                        [hashlib.sha256(path.read_bytes()).hexdigest() for path in frame_paths],
                    )
                    self.assertTrue(all(image.meta == {"codex/imageDetail": "original"} for image in images))
                    with Image.open(frame_paths[0]) as rendered:
                        self.assertEqual(rendered.size, (128, 128))
                        self.assertEqual(rendered.getpixel((0, 0)), hex_to_rgb(COLOR_MAP[0]))
                    with Image.open(frame_paths[1]) as rendered:
                        self.assertEqual(rendered.getpixel((0, 0)), hex_to_rgb(COLOR_MAP[1]))

                    first_action = await session.call_tool("ACTION1", {})
                    self.assertFalse(first_action.isError)
                    unavailable = await session.call_tool("ACTION1", {})
                    self.assertTrue(unavailable.isError)
                    click = await session.call_tool("ACTION6", {"x": 12, "y": 34})
                    self.assertFalse(click.isError)
                    self.assertEqual(click.structuredContent["action_input"], {"id": 6, "data": {"x": 12, "y": 34}})
                    invalid_click = await session.call_tool("ACTION6", {"x": -1, "y": 0})
                    self.assertTrue(invalid_click.isError)

                    same = await session.call_tool("RESET", {"game_id": "game-a"})
                    self.assertFalse(same.isError)
                    different = await session.call_tool("RESET", {"game_id": "game-b"})
                    self.assertTrue(different.isError)

            state = json.loads(state_path.read_text())
            self.assertEqual(state["game_id"], "game-a")
            self.assertFalse(state["closed"])
            command_names = [name for name, _payload in self.server.state.commands]
            self.assertEqual(command_names, ["RESET", "ACTION1", "ACTION6", "RESET"])
            action6_payload = next(payload for name, payload in self.server.state.commands if name == "ACTION6")
            self.assertEqual((action6_payload["x"], action6_payload["y"]), (12, 34))
            self.assertNotIn("reasoning", action6_payload)
            final_reset = self.server.state.commands[-1][1]
            self.assertEqual(final_reset["guid"], state["guid"])
            self.assertEqual(final_reset["card_id"], state["card_id"])
            self.assertFalse(any(name == "CLOSE" for name in command_names))

    async def test_two_stdio_processes_keep_rollout_state_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_a, state_a, _ = _write_context(root, "a", self.server.base_url, ["game-a"])
            context_b, state_b, _ = _write_context(root, "b", self.server.base_url, ["game-b"])
            for context, game in ((context_a, "game-a"), (context_b, "game-b")):
                async with stdio_client(_parameters(context)) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        result = await session.call_tool("RESET", {"game_id": game})
                        self.assertFalse(result.isError)
            private_a = json.loads(state_a.read_text())
            private_b = json.loads(state_b.read_text())
            self.assertEqual(private_a["game_id"], "game-a")
            self.assertEqual(private_b["game_id"], "game-b")
            self.assertNotEqual(private_a["card_id"], private_b["card_id"])
            self.assertNotEqual(private_a["guid"], private_b["guid"])

    def test_context_schema_modes_duplicates_and_secrecy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context, state, rollout = _write_context(root, "ok", self.server.base_url, ["game-a"])
            loaded = load_context(context)
            self.assertEqual(loaded.allowed_game_ids, ("game-a",))
            self.assertEqual(loaded.state_path, state)
            self.assertEqual(loaded.artifact_root, rollout / "arc_observations")
            self.assertNotIn(self.server.base_url, repr(loaded))
            self.assertNotIn(str(state), repr(loaded))

            duplicate, _, _ = _write_context(root, "duplicate", self.server.base_url, ["game-a", "game-a"])
            with self.assertRaisesRegex(ArcAgiMcpError, "invalid allowed games"):
                load_context(duplicate)
            unexpected, _, _ = _write_context(
                root, "unexpected", self.server.base_url, ["game-a"], extra={"ARC_API_KEY": "secret"}
            )
            with self.assertRaisesRegex(ArcAgiMcpError, "invalid schema"):
                load_context(unexpected)
            context.chmod(0o644)
            with self.assertRaisesRegex(ArcAgiMcpError, "0600"):
                load_context(context)

    def test_one_process_owns_each_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context, _, _ = _write_context(root, "lock", self.server.base_url, ["game-a"])
            first = _acquire_process_lock(context)
            try:
                with self.assertRaisesRegex(ArcAgiMcpError, "active command server"):
                    _acquire_process_lock(context)
            finally:
                fcntl.flock(first, fcntl.LOCK_UN)
                os.close(first)


if __name__ == "__main__":
    unittest.main()

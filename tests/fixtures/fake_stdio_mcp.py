#!/usr/bin/env python3
"""Offline stdio MCP fixture with text, secret, slow, and image/resource results."""

from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Annotated

pid_file = os.environ.get("FAKE_MCP_PID_FILE")
if pid_file:
    Path(pid_file).write_text(str(os.getpid()))
env_file = os.environ.get("FAKE_MCP_ENV_FILE")
if env_file:
    Path(env_file).write_text("\n".join(sorted(os.environ)) + "\n")
status_file = os.environ.get("FAKE_MCP_STATUS_FILE")
if status_file:
    Path(status_file).write_text(Path("/proc/self/status").read_text())

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent, TextResourceContents
from pydantic import Field, StrictInt

mcp = FastMCP("Metalanguage offline fixture", json_response=True)


def record_call(name: str, arguments: dict[str, object]) -> None:
    path = os.environ.get("FAKE_MCP_CALLS_FILE")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"tool": name, "arguments": arguments}, sort_keys=True) + "\n")


@mcp.tool()
def echo(text: str) -> str:
    return f"echo:{text}"


@mcp.tool()
def secret(answer: str) -> dict[str, str]:
    return {"answer": answer, "token": "sk-PRIVATE-MCP-RESULT"}


@mcp.tool()
def slow(seconds: int = 30) -> str:
    time.sleep(seconds)
    return "late"


@mcp.tool()
def image() -> CallToolResult:
    record_call("image", {})
    return fixture_result("image")


def fixture_result(name: str) -> CallToolResult:
    return CallToolResult(
        content=[
            TextContent(type="text", text=f"{name} fixture"),
            ImageContent(
                type="image",
                mimeType="image/png",
                data=(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4"
                    "z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
                ),
            ),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri="fixture://text",
                    mimeType="text/plain",
                    text="resource fixture",
                ),
            ),
        ]
    )


@mcp.tool(name="RESET")
def RESET(game_id: str) -> CallToolResult:
    record_call("RESET", {"game_id": game_id})
    return fixture_result("RESET")


def action(name: str, arguments: dict[str, object] | None = None) -> CallToolResult:
    record_call(name, arguments or {})
    return fixture_result(name)


@mcp.tool(name="ACTION1")
def ACTION1() -> CallToolResult:
    return action("ACTION1")


@mcp.tool(name="ACTION2")
def ACTION2() -> CallToolResult:
    return action("ACTION2")


@mcp.tool(name="ACTION3")
def ACTION3() -> CallToolResult:
    return action("ACTION3")


@mcp.tool(name="ACTION4")
def ACTION4() -> CallToolResult:
    return action("ACTION4")


@mcp.tool(name="ACTION5")
def ACTION5() -> CallToolResult:
    return action("ACTION5")


@mcp.tool(name="ACTION6")
def ACTION6(
    x: Annotated[StrictInt, Field(ge=0, le=63)],
    y: Annotated[StrictInt, Field(ge=0, le=63)],
) -> CallToolResult:
    return action("ACTION6", {"x": x, "y": y})


@mcp.tool(name="ACTION7")
def ACTION7() -> CallToolResult:
    return action("ACTION7")


if __name__ == "__main__":
    mcp.run(transport="stdio")

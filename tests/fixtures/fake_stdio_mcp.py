#!/usr/bin/env python3
"""Offline stdio MCP fixture with text, secret, slow, and image/resource results."""

from __future__ import annotations

import os
import time
from pathlib import Path

pid_file = os.environ.get("FAKE_MCP_PID_FILE")
if pid_file:
    Path(pid_file).write_text(str(os.getpid()))
env_file = os.environ.get("FAKE_MCP_ENV_FILE")
if env_file:
    Path(env_file).write_text("\n".join(sorted(os.environ)) + "\n")

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent, TextResourceContents

mcp = FastMCP("Metalanguage offline fixture", json_response=True)


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
    return CallToolResult(
        content=[
            TextContent(type="text", text="image fixture"),
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


if __name__ == "__main__":
    mcp.run(transport="stdio")

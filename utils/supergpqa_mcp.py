"""Per-rollout stdio MCP server for SuperGPQA benchmark tools."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from utils.supergpqa_submit import submit_solution as grade_submit_solution


HANDLER_CONTEXT_ENV = "METALANGUAGE_SUPERGPQA_CONTEXT"
mcp = FastMCP("SuperGPQA", json_response=True)


def _load_context() -> dict[str, Any]:
    raw_path = os.environ.get(HANDLER_CONTEXT_ENV)
    if not raw_path:
        raise RuntimeError("SuperGPQA handler context is not configured")
    path = Path(raw_path)
    if not path.is_absolute():
        raise RuntimeError("SuperGPQA handler context must be absolute")
    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("SuperGPQA handler context is unreadable") from None
    if not isinstance(context, dict):
        raise RuntimeError("SuperGPQA handler context must be a JSON object")
    return context


_HANDLER_CONTEXT = _load_context()


@mcp.tool(structured_output=True)
def submit_solution(uuid: str, answer: str) -> dict[str, Any]:
    """Submit a shared-pool problem uuid and answer for immediate scoring."""

    try:
        return grade_submit_solution(
            context=_HANDLER_CONTEXT,
            args={"uuid": uuid, "answer": answer},
        )
    except Exception:
        return {"success": False, "error": "submit_solution failed"}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

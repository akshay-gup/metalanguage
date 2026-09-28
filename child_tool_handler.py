#!/usr/bin/env python3
"""Cold-start entrypoint for backend-independent child slot requests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from utils.child_spawn import _spawn_child_continuation, _spawn_failure


def run_child_tool_handler(context_path: Path) -> None:
    try:
        raw_payload = sys.stdin.read()
        payload = json.loads(raw_payload) if raw_payload.strip() else {}
        context = json.loads(context_path.read_text(encoding="utf-8"))
        if not isinstance(context, dict) or not isinstance(payload, dict):
            raise ValueError("handler context and payload must be JSON objects")
        tool = payload.get("tool")
        raw_args = payload.get("arguments")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        if tool == "spawn_child":
            result = _spawn_child_continuation(context=context, args=args)
        else:
            result = _spawn_failure(
                f"unsupported dynamic tool: {tool}",
                error_code="unsupported_dynamic_tool",
                retryable=True,
            )
    except BaseException as exc:
        result = _spawn_failure(
            f"{type(exc).__name__}: {exc}",
            error_code="spawn_child_handler_failed",
            retryable=True,
        )

    result = {**result, "success": bool(result.get("success"))}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    run_child_tool_handler(Path(sys.argv[1]).expanduser().resolve())

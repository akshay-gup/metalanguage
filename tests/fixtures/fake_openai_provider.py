#!/usr/bin/env python3
"""Offline OpenAI-compatible streaming provider for real OpenCode integration tests."""

from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CAPTURE = Path(os.environ["FAKE_PROVIDER_CAPTURE"])
MODE = os.environ.get("FAKE_PROVIDER_MODE", "final")
TOOL_NAME = os.environ.get("FAKE_PROVIDER_TOOL", "spawn_child")
TOOL_ARGS = json.loads(os.environ.get("FAKE_PROVIDER_TOOL_ARGS", "{}"))
TOOL_PLAN = json.loads(os.environ.get("FAKE_PROVIDER_TOOL_PLAN", "[]"))


def chunk(handler: BaseHTTPRequestHandler, payload: object) -> None:
    handler.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        with CAPTURE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(request, sort_keys=True) + "\n")

        messages = request.get("messages", [])
        tool_results = [message for message in messages if message.get("role") == "tool"]
        has_tool_result = bool(tool_results)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        base = {
            "id": f"chatcmpl_fixture_{len(tool_results)}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "test-model",
        }
        plan_entry = (
            TOOL_PLAN[len(tool_results)]
            if isinstance(TOOL_PLAN, list) and len(tool_results) < len(TOOL_PLAN)
            else None
        )
        should_call_tool = (
            isinstance(plan_entry, dict)
            or MODE in {"spawn", "mcp"} and not has_tool_result
        )
        arguments = (
            plan_entry.get("arguments", {}) if isinstance(plan_entry, dict) else TOOL_ARGS
        )
        tool_name = (
            plan_entry.get("tool", TOOL_NAME) if isinstance(plan_entry, dict) else TOOL_NAME
        )
        if should_call_tool:
            chunk(
                self,
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": f"call_fixture_{len(tool_results)}",
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(arguments),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ],
                },
            )
            chunk(
                self,
                {
                    **base,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "tool_calls"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        else:
            text = (
                "parent continued"
                if MODE.startswith("spawn")
                else "offline final assistant"
            )
            chunk(
                self,
                {
                    **base,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": text},
                            "finish_reason": None,
                        }
                    ],
                },
            )
            chunk(
                self,
                {
                    **base,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        handler = self
        handler.wfile.write(b"data: [DONE]\n\n")
        handler.wfile.flush()


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(f"http://127.0.0.1:{server.server_port}/v1", flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass

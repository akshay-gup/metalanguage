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
TRANSPORT_CAPTURE = (
    Path(os.environ["FAKE_PROVIDER_TRANSPORT_CAPTURE"])
    if os.environ.get("FAKE_PROVIDER_TRANSPORT_CAPTURE")
    else None
)
MODE = os.environ.get("FAKE_PROVIDER_MODE", "final")
TOOL_NAME = os.environ.get("FAKE_PROVIDER_TOOL", "spawn_child")
TOOL_ARGS = json.loads(os.environ.get("FAKE_PROVIDER_TOOL_ARGS", "{}"))
TOOL_PLAN = json.loads(os.environ.get("FAKE_PROVIDER_TOOL_PLAN", "[]"))
RELEASE_AFTER_CAPTURE = (
    Path(os.environ["FAKE_PROVIDER_RELEASE_AFTER_CAPTURE"])
    if os.environ.get("FAKE_PROVIDER_RELEASE_AFTER_CAPTURE")
    else None
)


def chunk(handler: BaseHTTPRequestHandler, payload: object) -> None:
    handler.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/v1/chat/completions", "/v1/responses"}:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        with CAPTURE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(request, sort_keys=True) + "\n")
        if RELEASE_AFTER_CAPTURE is not None and not RELEASE_AFTER_CAPTURE.exists():
            deadline = time.monotonic() + 5
            while not RELEASE_AFTER_CAPTURE.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not RELEASE_AFTER_CAPTURE.exists():
                self.send_error(504)
                return
        if TRANSPORT_CAPTURE is not None:
            with TRANSPORT_CAPTURE.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "path": self.path,
                            "headers": {
                                name.lower(): value for name, value in self.headers.items()
                            },
                            "model": request.get("model"),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )

        if MODE == "error":
            reflected = (
                f"provider rejected {self.headers.get('Authorization', '')} "
                f"{self.headers.get('X-Custom-Secret', '')}"
            )
            body = json.dumps({"error": {"message": reflected, "type": "fixture_error"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return

        if self.path == "/v1/responses":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            response_id = "resp_fixture"
            item_id = "msg_fixture"
            for payload in (
                {
                    "type": "response.created",
                    "response": {
                        "id": response_id,
                        "created_at": int(time.time()),
                        "model": request.get("model"),
                        "service_tier": None,
                    },
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "message",
                        "id": item_id,
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    },
                },
                {
                    "type": "response.content_part.added",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
                {
                    "type": "response.output_text.delta",
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "offline final assistant",
                    "logprobs": None,
                },
                {
                    "type": "response.output_item.done",
                    "output_index": 0,
                    "item": {
                        "type": "message",
                        "id": item_id,
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "offline final assistant",
                                "annotations": [],
                            }
                        ],
                    },
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": response_id,
                        "incomplete_details": None,
                        "service_tier": None,
                        "usage": {
                            "input_tokens": 1,
                            "input_tokens_details": None,
                            "output_tokens": 1,
                            "output_tokens_details": None,
                        },
                    },
                },
            ):
                chunk(self, payload)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

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

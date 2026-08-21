#!/usr/bin/env python3
"""Local fake for the source-audited OpenCode HTTP/SSE boundary."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


if "--version" in sys.argv:
    print(os.environ.get("FAKE_OPENCODE_VERSION", "1.18.18"))
    raise SystemExit(0)


events: queue.Queue[str | None] = queue.Queue()
config = json.loads(os.environ.get("OPENCODE_CONFIG_CONTENT", "{}"))


def json_response(handler: BaseHTTPRequestHandler, payload: object, status: int = 200) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/event":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(
                b'data: {"id":"connected","type":"server.connected","properties":{}}\n\n'
            )
            self.wfile.flush()
            while True:
                item = events.get()
                if item is None:
                    return
                self.wfile.write(f"data: {item}\n\n".encode())
                self.wfile.flush()
        elif path == "/mcp":
            status = {}
            for name, server in config.get("mcp", {}).items():
                command = server.get("command", [])
                status[name] = {
                    "status": "failed" if "fake-fail" in command else "connected",
                    **({"error": "fixture failure"} if "fake-fail" in command else {}),
                }
            json_response(self, status)
        else:
            json_response(self, {"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if path == "/session":
            directory = Path(self._directory())
            (directory / "fake_session.json").write_text(
                json.dumps(payload, sort_keys=True)
            )
            json_response(self, {"id": "ses_fixture", "directory": self._directory()})
            return
        if path.endswith("/abort"):
            events.put(
                json.dumps(
                    {
                        "type": "session.status",
                        "properties": {"sessionID": "ses_fixture", "status": {"type": "idle"}},
                    }
                )
            )
            json_response(self, True)
            return
        if path == "/session/ses_fixture/message":
            directory = Path(self._directory())
            (directory / "fake_prompt.json").write_text(json.dumps(payload, sort_keys=True))
            (directory / "fake_server.pid").write_text(str(os.getpid()))
            state = {
                key: os.environ.get(key)
                for key in [
                    "HOME",
                    "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME",
                    "XDG_STATE_HOME",
                    "XDG_CACHE_HOME",
                    "TMPDIR",
                    "OPENCODE_DB",
                    "METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS",
                ]
            }
            state["spawn_child_tool"] = Path(
                os.environ["OPENCODE_CONFIG_DIR"], "tool", "spawn_child.js"
            ).is_file()
            state["system_plugin"] = Path(
                os.environ["OPENCODE_CONFIG_DIR"], "plugin", "metalanguage_system.js"
            ).is_file()
            (directory / "fake_state.json").write_text(json.dumps(state, sort_keys=True))
            text = payload["parts"][0]["text"]
            events.put(
                json.dumps(
                    {
                        "type": "session.status",
                        "properties": {"sessionID": "ses_fixture", "status": {"type": "busy"}},
                    }
                )
            )
            if text == "__MALFORMED__":
                events.put("{not-json}")
                time.sleep(60)
                return
            if text == "__PROVIDER_ERROR__":
                events.put(
                    json.dumps(
                        {
                            "type": "session.error",
                            "properties": {
                                "sessionID": "ses_fixture",
                                "error": {
                                    "name": "ProviderAuthError",
                                    "data": {"message": "fixture provider failure"},
                                },
                            },
                        }
                    )
                )
                json_response(self, {"info": {}, "parts": []})
                return
            if text == "__TIMEOUT__":
                time.sleep(60)
                return
            if text == "__DESCENDANT__":
                descendant = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"]
                )
                (directory / "fake_descendant.pid").write_text(str(descendant.pid))
            if config.get("mcp"):
                events.put(
                    json.dumps(
                        {
                            "type": "message.part.updated",
                            "properties": {
                                "part": {
                                    "id": "tool_fixture",
                                    "sessionID": "ses_fixture",
                                    "type": "tool",
                                    "tool": "mcp__supergpqa__submit_solution",
                                    "state": {
                                        "status": "running",
                                        "input": {"answer": "SECRET_ARGUMENT"},
                                    },
                                }
                            },
                        }
                    )
                )
                events.put(
                    json.dumps(
                        {
                            "type": "message.part.updated",
                            "properties": {
                                "part": {
                                    "id": "tool_fixture",
                                    "sessionID": "ses_fixture",
                                    "type": "tool",
                                    "tool": "mcp__supergpqa__submit_solution",
                                    "state": {
                                        "status": "completed",
                                        "input": {"answer": "SECRET_ARGUMENT"},
                                        "output": "SECRET_RESULT",
                                    },
                                }
                            },
                        }
                    )
                )
            if text == "__SPAWN__":
                for status, result in [("running", None), ("completed", {"success": True})]:
                    events.put(
                        json.dumps(
                            {
                                "type": "message.part.updated",
                                "properties": {
                                    "part": {
                                        "id": "spawn_fixture",
                                        "sessionID": "ses_fixture",
                                        "type": "tool",
                                        "tool": "spawn_child",
                                        "state": {
                                            "status": status,
                                            "input": {"prompt": "child", "workspace_dir": "seed"},
                                            **({"output": result} if result is not None else {}),
                                        },
                                    }
                                },
                            }
                        )
                    )
            final = "parent continued" if text == "__SPAWN__" else "fixture final"
            events.put(
                json.dumps(
                    {
                        "type": "message.part.updated",
                        "properties": {
                            "part": {
                                "id": "text_fixture",
                                "sessionID": "ses_fixture",
                                "type": "text",
                                "text": final,
                                "time": {"start": 1, "end": 2},
                            }
                        },
                    }
                )
            )
            events.put(
                json.dumps(
                    {
                        "type": "session.status",
                        "properties": {"sessionID": "ses_fixture", "status": {"type": "idle"}},
                    }
                )
            )
            json_response(
                self,
                {
                    "info": {"id": "msg_fixture", "role": "assistant"},
                    "parts": [{"type": "text", "text": final}],
                },
            )
            return
        json_response(self, {"error": "not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        json_response(self, True)

    def _directory(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return query.get("directory", [os.getcwd()])[0]


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
print(f"opencode server listening on http://127.0.0.1:{server.server_port}", flush=True)
server.serve_forever()

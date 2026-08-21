#!/usr/bin/env python3
"""Local fake for the source-audited OpenCode HTTP/SSE boundary."""

from __future__ import annotations

import json
import base64
import hashlib
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


def host_pid(pid: int | None = None) -> int:
    target = "self" if pid is None else str(pid)
    for line in Path(f"/proc/{target}/status").read_text().splitlines():
        if line.startswith("NSpid:"):
            return int(line.split()[1])
    return os.getpid() if pid is None else pid


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
        if not self._authorized():
            return
        path = urlparse(self.path).path
        if path == "/event":
            if os.environ.get("FAKE_OPENCODE_SSE_HANG") == "1":
                time.sleep(60)
                return
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
                failed = any("fake-fail" in str(item) for item in command)
                status[name] = {
                    "status": "failed" if failed else "connected",
                    **({"error": "fixture failure"} if failed else {}),
                }
            json_response(self, status)
        else:
            json_response(self, {"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
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
            (directory / "fake_server.pid").write_text(str(host_pid()))
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
            config_dir = Path(os.environ["OPENCODE_CONFIG_DIR"])
            state["prepared_dependencies"] = all(
                (dependency_dir / name).exists()
                for dependency_dir in (config_dir, config_dir / "opencode")
                for name in ("node_modules", "package.json", "package-lock.json", ".gitignore")
            )
            state["npm_offline"] = os.environ.get("npm_config_offline") == "true"
            state["server_port"] = self.server.server_port
            state["auth_fingerprint"] = hashlib.sha256(
                os.environ["OPENCODE_SERVER_PASSWORD"].encode()
            ).hexdigest()
            state["environment_names"] = sorted(os.environ)
            state["unrelated_home_visible"] = Path("/home/akshay/.ssh").exists()
            project_env = Path(
                os.environ["METALANGUAGE_OPENCODE_WORKER_SCRIPT"]
            ).parents[2] / ".env"
            state["project_env_masked"] = project_env.exists() and project_env.stat().st_size == 0
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
            events.put(
                json.dumps(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_user",
                                "sessionID": "ses_fixture",
                                "role": "user",
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
                                "id": "text_user",
                                "messageID": "msg_user",
                                "sessionID": "ses_fixture",
                                "type": "text",
                                "text": text,
                            }
                        },
                    }
                )
            )
            if text == "__RETRY__":
                events.put(
                    json.dumps(
                        {
                            "type": "session.status",
                            "properties": {
                                "sessionID": "ses_fixture",
                                "status": {"type": "retry"},
                            },
                        }
                    )
                )
            if text == "__MALFORMED__":
                events.put('{"secret":"sk-PRIVATE-MALFORMED"')
                time.sleep(60)
                return
            if text == "__HTTP_ERROR__":
                json_response(self, {"secret": "sk-PRIVATE-HTTP-BODY"}, 500)
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
                                    "data": {"message": "fixture provider failure sk-PRIVATE-PROVIDER"},
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
                (directory / "fake_descendant.pid").write_text(str(host_pid(descendant.pid)))
            events.put(
                json.dumps(
                    {
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_intermediate",
                                "sessionID": "ses_fixture",
                                "role": "assistant",
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
                                "id": "text_intermediate",
                                "messageID": "msg_intermediate",
                                "sessionID": "ses_fixture",
                                "type": "text",
                                "text": "intermediate assistant tool request",
                                "time": {"start": 1, "end": 2},
                            }
                        },
                    }
                )
            )
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
                        "type": "message.updated",
                        "properties": {
                            "info": {
                                "id": "msg_fixture",
                                "sessionID": "ses_fixture",
                                "role": "assistant",
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
                                "id": "text_fixture",
                                "messageID": "msg_fixture",
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
                    "info": {
                        "id": "msg_fixture",
                        "sessionID": "ses_fixture",
                        "role": "assistant",
                    },
                    "parts": [
                        {
                            "id": "text_fixture",
                            "messageID": "msg_fixture",
                            "sessionID": "ses_fixture",
                            "type": "text",
                            "text": final,
                        }
                    ],
                },
            )
            return
        json_response(self, {"error": "not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        json_response(self, True)

    def _authorized(self) -> bool:
        username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
        password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
        expected = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        if self.headers.get("Authorization") == expected:
            return True
        json_response(self, {"error": "unauthorized sk-PRIVATE-AUTH"}, 401)
        return False

    def _directory(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return query.get("directory", [os.getcwd()])[0]


if os.environ.get("FAKE_OPENCODE_STARTUP_HANG") == "1":
    time.sleep(60)

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
print(f"opencode server listening on http://127.0.0.1:{server.server_port}", flush=True)
server.serve_forever()

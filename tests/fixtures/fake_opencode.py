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
    print(os.environ.get("FAKE_OPENCODE_VERSION", "1.18.29"))
    raise SystemExit(0)


events: queue.Queue[str | None] = queue.Queue()
config = json.loads(os.environ.get("OPENCODE_CONFIG_CONTENT", "{}"))
messages: list[dict[str, object]] = []
messages_lock = threading.Lock()


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


def no_content(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(204)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    handler.wfile.flush()


def record_request(directory: Path, method: str, path: str) -> None:
    with (directory / "fake_http_requests.jsonl").open("a") as stream:
        stream.write(json.dumps({"method": method, "path": path}) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        path = urlparse(self.path).path
        directory = Path(self._directory())
        record_request(directory, "GET", path)
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
                    self.close_connection = True
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
        elif path == "/session/ses_fixture/message":
            with messages_lock:
                json_response(self, list(messages))
        else:
            json_response(self, {"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        path = urlparse(self.path).path
        directory = Path(self._directory())
        record_request(directory, "POST", path)
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if path == "/session":
            (directory / "fake_session.json").write_text(
                json.dumps(payload, sort_keys=True)
            )
            json_response(self, {"id": "ses_fixture", "directory": self._directory()})
            return
        if path.endswith("/abort"):
            (directory / "fake_abort").write_text("aborted")
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
            (directory / "fake_sync_message_used").write_text("used")
            json_response(self, {"error": "synchronous message route forbidden"}, 405)
            return
        if path == "/session/ses_fixture/prompt_async":
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
                    "METALANGUAGE_SPAWN_CHILD_ENDPOINT",
                    "METALANGUAGE_SPAWN_CHILD_HANDLER_COMMAND",
                    "METALANGUAGE_OPENCODE_WORKER_SCRIPT",
                ]
            }
            state["tool_files"] = sorted(
                path.name
                for path in Path(
                    os.environ["OPENCODE_CONFIG_DIR"], "tool"
                ).glob("*.js")
            )
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
            state["path_environment"] = {}
            for name in (
                "GOOGLE_APPLICATION_CREDENTIALS",
                "REQUESTS_CA_BUNDLE",
                "SSL_CERT_DIR",
                "SSL_CERT_FILE",
            ):
                value = os.environ.get(name)
                if value is None:
                    continue
                path = Path(value)
                state["path_environment"][name] = {
                    "value": value,
                    "exists": path.exists(),
                    "is_dir": path.is_dir(),
                    "sha256": (
                        hashlib.sha256(path.read_bytes()).hexdigest()
                        if path.is_file()
                        else None
                    ),
                }
                try:
                    if path.is_file():
                        path.write_bytes(path.read_bytes())
                    else:
                        (path / "metalanguage-write-probe").write_text("probe")
                    state["path_environment"][name]["writable"] = True
                except OSError:
                    state["path_environment"][name]["writable"] = False
            stable_parent = Path("/run/metalanguage/credentials")
            state["credential_mount_names"] = (
                sorted(path.name for path in stable_parent.iterdir())
                if stable_parent.is_dir()
                else []
            )
            masked_path = os.environ.get("METALANGUAGE_OPENCODE_MASKED_PATH")
            state["project_env_masked"] = bool(
                masked_path
                and Path(masked_path).exists()
                and Path(masked_path).stat().st_size == 0
            )
            (directory / "fake_state.json").write_text(json.dumps(state, sort_keys=True))
            text = payload["parts"][0]["text"]
            if text == "__HTTP_ERROR__":
                json_response(self, {"secret": "sk-PRIVATE-HTTP-BODY"}, 500)
                return
            if text == "__SUBMIT_HANG__":
                time.sleep(60)
                return
            (directory / "fake_prompt_accepted_at").write_text(str(time.monotonic()))
            no_content(self)
            if text == "__INITIAL_IDLE__":
                events.put(
                    json.dumps(
                        {
                            "type": "session.status",
                            "properties": {"sessionID": "ses_fixture", "status": {"type": "idle"}},
                        }
                    )
                )
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
                return
            if text == "__SSE_DISCONNECT__":
                events.put(None)
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
                return
            if text == "__TIMEOUT__":
                return
            if text == "__LONG_ASYNC__":
                time.sleep(1.2)
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
            user_message_id = payload["messageID"]
            with messages_lock:
                messages[:] = [
                    {
                        "info": {
                            "id": user_message_id,
                            "sessionID": "ses_fixture",
                            "role": "user",
                        },
                        "parts": [
                            {
                                "id": "text_user",
                                "messageID": user_message_id,
                                "sessionID": "ses_fixture",
                                "type": "text",
                                "text": text,
                            }
                        ],
                    },
                    {
                        "info": {
                            "id": "msg_fixture",
                            "parentID": user_message_id,
                            "sessionID": "ses_fixture",
                            "role": "assistant",
                            "finish": "stop",
                            "time": {"created": 1, "completed": 2},
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
                    {
                        "info": {
                            "id": "msg_unrelated",
                            "parentID": "msg_other_turn",
                            "sessionID": "ses_fixture",
                            "role": "assistant",
                            "finish": "stop",
                        },
                        "parts": [
                            {
                                "id": "text_unrelated",
                                "messageID": "msg_unrelated",
                                "sessionID": "ses_fixture",
                                "type": "text",
                                "text": "wrong turn response",
                            }
                        ],
                    },
                ]
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
            (directory / "fake_prompt_completed_at").write_text(str(time.monotonic()))
            return
        json_response(self, {"error": "not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        directory = Path(self._directory())
        record_request(directory, "DELETE", urlparse(self.path).path)
        (directory / "fake_delete").write_text("deleted")
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

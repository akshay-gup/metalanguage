#!/usr/bin/env python3
"""Provider-free fake for exercising the launcher's stock CLI boundary contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def output(value: object) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def find_secret(value: object, sensitive: bool = False) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            result = find_secret(
                child,
                sensitive
                or any(marker in str(key).lower() for marker in ("token", "secret", "key", "auth")),
            )
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = find_secret(child, sensitive)
            if result:
                return result
    elif sensitive and isinstance(value, str) and len(value) >= 8:
        return value
    return None


def invoke_hook(event: dict[str, object]) -> dict[str, object]:
    study = Path(os.environ["CONTROL_STUDY_ROOT"])
    result = subprocess.run(
        [sys.executable, str(study / "hooks/iteration_boundary.py")],
        input=json.dumps(event).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace"))
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def main() -> int:
    args = sys.argv[1:]
    if args == ["--version"]:
        print("codex-cli 0.146.0")
        return 0
    if args[-2:] == ["features", "list"]:
        print("multi_agent stable false")
        print("multi_agent_v2 stable false")
        return 0
    if "debug" in args and "prompt-input" in args:
        prompt = args[-1]
        instruction = (Path.cwd() / "AGENTS.md").read_text(encoding="utf-8")
        print(json.dumps([{"role": "developer", "content": instruction}, {"role": "user", "content": prompt}]))
        return 0
    if "debug" in args and "models" in args:
        print(
            json.dumps(
                [
                    {
                        "slug": "gpt-5.6-sol",
                        "base_instructions": "stock fake built-ins",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                        ],
                    }
                ]
            )
        )
        return 0
    if "sandbox" in args:
        command = args[args.index("--") + 1 :]
        return subprocess.run(command).returncode
    if not args or args[0] != "exec":
        print(f"unsupported fake invocation: {args}", file=sys.stderr)
        return 2

    index = int(os.environ["CONTROL_ROLLOUT_INDEX"])
    codex_home = Path(os.environ["CODEX_HOME"])
    session_file = codex_home / "fake_session_id"
    resume = len(args) > 1 and args[1] == "resume"
    if resume:
        prompt = args[-1]
        supplied_session = args[-2]
        session_id = session_file.read_text(encoding="utf-8")
        if supplied_session != session_id:
            print("wrong session id", file=sys.stderr)
            return 3
    else:
        prompt = args[-1]
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(codex_home.resolve())))
        session_file.write_text(session_id, encoding="utf-8")

    started = time.time()
    output({"type": "thread.started", "thread_id": session_id})
    output({"type": "tool.inventory", "tools": ["exec_command", "apply_patch"]})
    output(
        {
            "type": "fake.invocation",
            "fresh": not resume,
            "prompt": prompt,
            "rollout_index": index,
            "started": started,
            "shared_realpath": str((Path.cwd() / "shared_workspace").resolve()),
            "archive_realpath": str((Path.cwd() / "archive").resolve()),
            "archive_device": (Path.cwd() / "archive").stat().st_dev,
            "archive_inode": (Path.cwd() / "archive").stat().st_ino,
        }
    )
    event_base: dict[str, object] = {
        "session_id": session_id,
        "turn_id": f"turn-{index}",
        "cwd": str(Path.cwd()),
        "model": "gpt-5.6-sol",
    }
    stop_result = invoke_hook(event_base | {"hook_event_name": "Stop", "stop_hook_active": False})
    output({"type": "fake.stop_hook", "result": stop_result})
    incomplete = os.environ.get("FAKE_INCOMPLETE_ROLLOUT") == str(index)
    time.sleep(float(os.environ.get("FAKE_CODEX_DELAY", "0.06")))
    if incomplete:
        output({"type": "error", "message": "fake pre-compaction failure"})
        return 9
    post_result = invoke_hook(
        event_base | {"hook_event_name": "PostCompact", "trigger": "auto"}
    )
    output({"type": "fake.post_compact_hook", "result": post_result})
    message = f"fake rollout {index} stopped after auto compaction"
    if os.environ.get("FAKE_PRINT_AUTH") == "1":
        auth = json.loads((codex_home / "auth.json").read_text(encoding="utf-8"))
        secret = find_secret(auth)
        if secret:
            message += f" {secret}"
            print(f"fake stderr {secret}", file=sys.stderr, flush=True)
    output({"type": "item.completed", "item": {"type": "agent_message", "text": message}})
    output({"type": "turn.completed", "ended": time.time()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Codex hook: load AGENTS.md from the exact directory used by a tool call."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


MAX_AGENTS_BYTES = 8 * 1024


def _managed_roots(context: dict[str, Any]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for key in ("workdir", "shared_archives_root", "shared_workspace_dir"):
        value = context.get(key)
        if isinstance(value, str) and value:
            try:
                root = Path(value).expanduser().resolve(strict=True)
            except OSError:
                continue
            if root.is_dir() and root not in roots:
                roots.append(root)
    return tuple(roots)


def _tool_directory(payload: dict[str, Any], root: Path) -> Path:
    tool_input = payload.get("tool_input")
    arguments = tool_input if isinstance(tool_input, dict) else {}
    for key in ("workdir", "working_directory", "cwd", "directory"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            return path.resolve() if path.is_absolute() else (root / path).resolve()
    for key in ("filePath", "file_path", "path"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            path = path.resolve() if path.is_absolute() else (root / path).resolve()
            return path if path.is_dir() else path.parent
    return root


def _read_agents(directory: Path) -> tuple[Path, str, str] | None:
    candidate = directory / "AGENTS.md"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            candidate,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_AGENTS_BYTES:
            return None
        content_bytes = os.read(descriptor, MAX_AGENTS_BYTES + 1)
        if len(content_bytes) > MAX_AGENTS_BYTES:
            return None
        content = content_bytes.decode("utf-8")
        if not content.strip():
            return None
        return candidate, hashlib.sha256(content_bytes).hexdigest(), content
    except (OSError, UnicodeError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _first_load(state_path: Path, key: str) -> bool:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("a+", encoding="utf-8") as state:
        os.chmod(state_path, 0o600)
        fcntl.flock(state.fileno(), fcntl.LOCK_EX)
        state.seek(0)
        if key in {line.rstrip("\n") for line in state}:
            return False
        state.write(key + "\n")
        state.flush()
        return True


def main() -> None:
    if len(sys.argv) != 2:
        return
    try:
        context_path = Path(sys.argv[1]).expanduser().resolve(strict=True)
        context = json.loads(context_path.read_text(encoding="utf-8"))
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(context, dict) or not isinstance(payload, dict):
            return
        roots = _managed_roots(context)
        if not roots:
            return
        directory = _tool_directory(payload, roots[0])
        containing_roots = [root for root in roots if directory == root or root in directory.parents]
        if not containing_roots or ".git" in directory.parts:
            return
        loaded = _read_agents(directory)
        if loaded is None:
            return
        path, digest, content = loaded
        key = f"{path}\t{digest}"
        if not _first_load(context_path.with_name("directory_agents_seen"), key):
            return
        observation = (
            f"# AGENTS.md instructions for {directory}\n\n"
            f"<INSTRUCTIONS>\n{content.rstrip()}\n</INSTRUCTIONS>"
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": observation,
                    }
                },
                ensure_ascii=False,
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        return


if __name__ == "__main__":
    main()

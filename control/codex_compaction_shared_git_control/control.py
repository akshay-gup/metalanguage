#!/usr/bin/env python3
"""Deterministic launcher for the standalone stock-Codex compaction control."""

from __future__ import annotations

import argparse
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable
import uuid


ROLLOUT_COUNT = 8
MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "low"
EXPECTED_CODEX_VERSION = "codex-cli 0.146.0"
INITIAL_BRANCH = "main"
FRESH_PROMPT = "Begin."
CONTINUATION_INPUT = "Continue until the next automatic compaction boundary."
FORBIDDEN_COLLABORATION_TOOLS = {
    "spawn_agent",
    "send_input",
    "resume_agent",
    "wait_agent",
    "close_agent",
    "spawn_child",
    "send_message",
}
class ControlError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    atomic_write(
        path,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        mode,
    )


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError(f"could not read valid JSON from {path}: {exc}") from None


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        if len(detail) > 1200:
            detail = detail[:1200] + "..."
        raise ControlError(
            f"command failed ({shlex.join(args)}): {detail or result.returncode}"
        )
    return result


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return _run(["git", "-C", str(repo), *args], env=environment, check=check)


def lstat_identity(path: Path) -> dict[str, Any]:
    info = path.lstat()
    return {
        "path": str(path),
        "resolved": str(path.resolve(strict=True)),
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IFMT(info.st_mode),
        "is_symlink": stat.S_ISLNK(info.st_mode),
    }


def ensure_real_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ControlError(f"{label} must not be a symlink: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ControlError(f"{label} is not a directory: {path}")
    if resolved != path.absolute():
        raise ControlError(f"{label} path is not canonical: {path}")
    return resolved


def repository_git_dir(repo: Path) -> Path:
    raw = git(repo, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
    git_dir = Path(raw)
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise ControlError("archive .git must be an ordinary private directory")
    expected = repo / ".git"
    if git_dir.resolve(strict=True) != expected.resolve(strict=True):
        raise ControlError("archive uses external or shared Git metadata")
    if (git_dir / "commondir").exists():
        raise ControlError("archive uses a shared common Git directory")
    if (git_dir / "objects/info/alternates").exists():
        raise ControlError("archive uses alternate object storage")
    return git_dir


def git_operation_state(repo: Path) -> str | None:
    git_dir = repository_git_dir(repo)
    if (git_dir / "rebase-merge").exists():
        return "rebase"
    rebase_apply = git_dir / "rebase-apply"
    if rebase_apply.exists():
        return "am" if (rebase_apply / "applying").exists() else "rebase"
    marker_states = [
        state_name
        for marker, state_name in (
            ("CHERRY_PICK_HEAD", "cherry-pick"),
            ("REVERT_HEAD", "revert"),
            ("MERGE_HEAD", "merge"),
        )
        if (git_dir / marker).exists()
    ]
    if len(marker_states) > 1:
        raise ControlError("conflicting Git integration-operation markers")
    if marker_states:
        return marker_states[0]
    if any(git_dir.glob("BISECT_*")):
        raise ControlError("unrecognized Git bisect operation")
    if (git_dir / "REBASE_HEAD").exists():
        raise ControlError("unrecognized standalone Git rebase marker")
    sequencer = git_dir / "sequencer"
    if not sequencer.exists():
        return None
    try:
        lines = (sequencer / "todo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise ControlError("unreadable Git sequencer operation") from None
    commands = [
        line.split(maxsplit=1)[0]
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if commands and set(commands) <= {"pick"}:
        return "cherry-pick"
    if commands and set(commands) <= {"revert"}:
        return "revert"
    raise ControlError("unrecognized Git sequencer operation")


def git_lock_paths(repo: Path) -> list[str]:
    git_dir = repository_git_dir(repo)
    return sorted(
        str(path.relative_to(git_dir))
        for path in git_dir.rglob("*")
        if path.is_file() and path.name.endswith(".lock")
    )


def git_refs_bytes(repo: Path) -> bytes:
    return git(
        repo,
        "for-each-ref",
        "--sort=refname",
        "--format=%(refname) %(objectname) %(symref)",
    ).stdout


def git_object_counts(repo: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in git(repo, "count-objects", "-v").stdout.decode().splitlines():
        key, separator, value = line.partition(": ")
        if separator and value.isdigit():
            result[key] = int(value)
    for required in ("count", "in-pack", "packs", "garbage"):
        if required not in result:
            raise ControlError(f"git count-objects omitted {required!r}")
    return result


def git_snapshot(repo: Path, *, include_ignored: bool = True) -> dict[str, Any]:
    branch_result = git(repo, "symbolic-ref", "-q", "HEAD", check=False)
    if branch_result.returncode not in {0, 1}:
        raise ControlError("could not inspect archive branch")
    branch = branch_result.stdout.decode().strip() if branch_result.returncode == 0 else None
    head_result = git(repo, "rev-parse", "--verify", "HEAD", check=False)
    if head_result.returncode == 0:
        head: str | None = head_result.stdout.decode().strip()
        unborn = False
    else:
        if branch is None:
            raise ControlError("archive HEAD is invalid rather than unborn")
        branch_exists = git(repo, "show-ref", "--verify", "--quiet", branch, check=False)
        if branch_exists.returncode != 1:
            raise ControlError("could not distinguish an unborn archive HEAD")
        head = None
        unborn = True
    status_args = ["status", "--porcelain=v2", "--untracked-files=all"]
    if include_ignored:
        status_args.append("--ignored=matching")
    status_output = git(repo, *status_args).stdout.decode("utf-8", "replace")
    refs = git_refs_bytes(repo)
    tree = git(repo, "ls-tree", "-r", "--full-tree", "HEAD").stdout if head else None
    tracked = git(repo, "ls-files", "--stage").stdout
    remotes = git(repo, "remote").stdout.decode().splitlines()
    return {
        "at": utc_now(),
        "identity": {
            "root": lstat_identity(repo),
            "git_dir": lstat_identity(repository_git_dir(repo)),
        },
        "head": head,
        "unborn": unborn,
        "branch": branch,
        "refs": refs.decode("utf-8", "replace").splitlines(),
        "refs_sha256": sha256_bytes(refs),
        "head_tree_sha256": sha256_bytes(tree) if tree is not None else None,
        "tracked_file_count": len(tracked.splitlines()),
        "tracked_index_sha256": sha256_bytes(tracked),
        "object_counts": git_object_counts(repo),
        "status": status_output.splitlines(),
        "operation_state": git_operation_state(repo),
        "locks": git_lock_paths(repo),
        "remotes": remotes,
    }


def clean_status(snapshot: dict[str, Any]) -> bool:
    return not [line for line in snapshot["status"] if not line.startswith("# branch.")]


def empty_repository_pin() -> dict[str, Any]:
    return {
        "kind": "empty-unborn-git-repository",
        "initial_branch": f"refs/heads/{INITIAL_BRANCH}",
        "head": None,
        "unborn": True,
        "refs_count": 0,
        "refs_sha256": sha256_bytes(b""),
        "head_tree_sha256": None,
        "tracked_file_count": 0,
        "tracked_index_sha256": sha256_bytes(b""),
        "loose_object_count": 0,
        "packed_object_count": 0,
        "remote_count": 0,
    }


def verify_initial_empty_repository(repo: Path) -> dict[str, Any]:
    snapshot = git_snapshot(repo)
    expected = empty_repository_pin()
    actual = {
        "kind": expected["kind"],
        "initial_branch": snapshot["branch"],
        "head": snapshot["head"],
        "unborn": snapshot["unborn"],
        "refs_count": len(snapshot["refs"]),
        "refs_sha256": snapshot["refs_sha256"],
        "head_tree_sha256": snapshot["head_tree_sha256"],
        "tracked_file_count": snapshot["tracked_file_count"],
        "tracked_index_sha256": snapshot["tracked_index_sha256"],
        "loose_object_count": snapshot["object_counts"]["count"],
        "packed_object_count": snapshot["object_counts"]["in-pack"],
        "remote_count": len(snapshot["remotes"]),
    }
    if actual != expected:
        raise ControlError(f"archive is not the pinned empty unborn repository: {actual}")
    if not clean_status(snapshot):
        raise ControlError("initial empty archive has working-tree or ignored content")
    entries = [entry.name for entry in repo.iterdir() if entry.name != ".git"]
    if entries:
        raise ControlError(f"initial empty archive has filesystem entries: {sorted(entries)}")
    git(repo, "fsck", "--full", "--no-reflogs", "--unreachable")
    return snapshot | {"empty_repository_identity": actual}


def create_initial_empty_repository(repo: Path) -> dict[str, Any]:
    if repo.exists() or repo.is_symlink():
        raise ControlError(f"empty archive destination already exists: {repo}")
    _run(["git", "init", "--initial-branch", INITIAL_BRANCH, str(repo)])
    git(repo, "config", "--local", "remote.pushDefault", "NO_PUSH_REMOTE")
    return verify_initial_empty_repository(repo)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_config(
    shared_workspace: Path,
    study_root: Path,
    codex_runtime_root: Path,
) -> str:
    shared = toml_string(str(shared_workspace))
    ceiling = toml_string(str(study_root))
    codex_runtime = toml_string(str(codex_runtime_root))
    return f'''# Generated by the base-Codex control. Runtime-local; do not hand edit.
model = {toml_string(MODEL)}
model_reasoning_effort = {toml_string(REASONING_EFFORT)}
approval_policy = "never"
default_permissions = "control"
web_search = "disabled"
project_doc_max_bytes = 32768

[agents]
enabled = false

[features]
hooks = true
multi_agent = false
multi_agent_v2 = false
apps = false
plugins = false
goals = false
memories = false
browser_use = false
browser_use_external = false
browser_use_full_cdp_access = false
computer_use = false
image_generation = false

[history]
persistence = "save-all"

[analytics]
enabled = false

[otel]
exporter = "none"
log_user_prompt = false

[shell_environment_policy]
inherit = "core"
ignore_default_excludes = false
set = {{ GIT_CEILING_DIRECTORIES = {ceiling} }}

[shell_environment_policy.filters]
"*PASSWORD*" = "exclude"
"*AUTH*" = "exclude"
"*CREDENTIAL*" = "exclude"

[permissions.control]
description = "Private rollout plus the one shared workspace, including Git metadata; no command network."

[permissions.control.workspace_roots]
{shared} = true

[permissions.control.filesystem]
":minimal" = "read"
{codex_runtime} = "read"

[permissions.control.filesystem.":workspace_roots"]
"." = "write"
"AGENTS.md" = "read"
"TASK.md" = "read"

[permissions.control.network]
enabled = false
'''


def render_hooks(study_root: Path, rollout_state: Path) -> dict[str, Any]:
    script = study_root / "hooks/iteration_boundary.py"
    command = (
        f"CONTROL_ROLLOUT_STATE_DIR={shlex.quote(str(rollout_state))} "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    )
    handler = {"type": "command", "command": command, "timeout": 30}
    return {
        "description": "One automatic-compaction iteration boundary.",
        "hooks": {
            "Stop": [{"hooks": [handler]}],
            "PostCompact": [{"matcher": "^auto$", "hooks": [handler]}],
        },
    }


def executable_identity(command: str) -> dict[str, Any]:
    located = shutil.which(command)
    if located is None:
        raise ControlError(f"executable is unavailable: {command}")
    launcher = Path(located).resolve(strict=True)
    result = _run([str(launcher), "--version"])
    version = result.stdout.decode().strip()
    identity: dict[str, Any] = {
        "command": command,
        "launcher": str(launcher),
        "launcher_sha256": sha256_file(launcher),
        "version": version,
    }
    package_root = launcher.parent.parent
    identity["installation_root"] = str(package_root.resolve(strict=True))
    native_candidates = sorted(package_root.glob("**/vendor/*/bin/codex"))
    if len(native_candidates) == 1:
        identity["native_binary"] = str(native_candidates[0].resolve())
        identity["native_binary_sha256"] = sha256_file(native_candidates[0])
    return identity


def offline_pinned_executable_identity(command: str, pins_path: Path) -> dict[str, Any]:
    pins = load_json(pins_path)
    codex_pin = pins.get("codex") if isinstance(pins, dict) else None
    if not isinstance(codex_pin, dict):
        raise ControlError("offline initialization requires codex pins")
    located = shutil.which(command)
    if located is None:
        raise ControlError(f"executable is unavailable: {command}")
    launcher = Path(located).resolve(strict=True)
    package_root = launcher.parent.parent.resolve(strict=True)
    native_candidates = sorted(package_root.glob("**/vendor/*/bin/codex"))
    if len(native_candidates) != 1:
        raise ControlError("offline initialization could not identify one stock native binary")
    identity = {
        "command": command,
        "launcher": str(launcher),
        "launcher_sha256": sha256_file(launcher),
        "version": codex_pin.get("version"),
        "installation_root": str(package_root),
        "native_binary": str(native_candidates[0].resolve(strict=True)),
        "native_binary_sha256": sha256_file(native_candidates[0]),
        "identity_source": "hash-verified seed/PINS.json; executable not launched",
    }
    for key in (
        "version",
        "launcher_sha256",
        "native_binary_sha256",
        "installation_root",
    ):
        if codex_pin.get(key) != identity.get(key):
            raise ControlError(f"offline stock Codex identity changed at {key}")
    return identity


def rollout_name(index: int) -> str:
    return f"rollout_{index:03d}"


@dataclass(frozen=True)
class Study:
    root: Path
    codex_command: str = "codex"

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def shared_workspace(self) -> Path:
        return self.runtime / "shared_workspace"

    @property
    def archive(self) -> Path:
        return self.shared_workspace / "archive"

    @property
    def study_state_path(self) -> Path:
        return self.runtime / "study_state.json"

    def rollout_dir(self, index: int) -> Path:
        return self.runtime / "rollouts" / rollout_name(index)

    def rollout_state(self, index: int) -> Path:
        return self.runtime / "state" / rollout_name(index)

    def codex_home(self, index: int) -> Path:
        return self.rollout_state(index) / "codex_home"

    def codex_env(self, index: int) -> dict[str, str]:
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.codex_home(index))
        environment["CONTROL_ROLLOUT_STATE_DIR"] = str(self.rollout_state(index))
        environment["CONTROL_STUDY_ROOT"] = str(self.root)
        environment["CONTROL_ROLLOUT_INDEX"] = str(index)
        environment["GIT_CEILING_DIRECTORIES"] = str(self.root)
        return environment


def seed_task_identity(seed_task: Path) -> dict[str, Any]:
    content = seed_task.read_bytes()
    digest = sha256_bytes(content)
    return {
        "sha256": digest,
        "bytes": len(content),
        "seed_path": str(seed_task),
        "source_identity": "previously captured exact task bytes; no live runtime dependency",
    }


def validate_seed_pins(
    study: Study,
    *,
    task_identity: dict[str, Any],
    codex_identity: dict[str, Any],
) -> dict[str, Any] | None:
    pins_path = study.root / "seed/PINS.json"
    if not pins_path.exists():
        return None
    pins = load_json(pins_path)
    if not isinstance(pins, dict):
        raise ControlError("seed/PINS.json is invalid")
    if pins.get("archive_initial_state") != empty_repository_pin():
        raise ControlError("seed/PINS.json does not pin the empty unborn archive")
    if pins.get("task", {}).get("sha256") != task_identity["sha256"]:
        raise ControlError("seed task no longer matches seed/PINS.json")
    if pins.get("task", {}).get("bytes") != task_identity["bytes"]:
        raise ControlError("seed task byte count no longer matches seed/PINS.json")
    instruction_hash = sha256_file(study.root / "seed/AGENTS.md")
    if pins.get("additive_instruction", {}).get("sha256") != instruction_hash:
        raise ControlError("additive instructions no longer match seed/PINS.json")
    codex_pin = pins.get("codex", {})
    for key in (
        "version",
        "launcher_sha256",
        "native_binary_sha256",
        "installation_root",
    ):
        if key in codex_pin and codex_pin[key] != codex_identity.get(key):
            raise ControlError(f"installed stock Codex no longer matches pin {key}")
    config_hash = sha256_bytes(
        render_config(
            study.root / "runtime/shared_workspace",
            study.root,
            Path(codex_identity["installation_root"]),
        ).encode()
    )
    if pins.get("experiment", {}).get("config_sha256") != config_hash:
        raise ControlError("generated experiment config no longer matches seed/PINS.json")
    return pins


def prepare_rollout_layout(
    study: Study,
    auth_file: Path,
    codex_identity: dict[str, Any],
) -> list[dict[str, Any]]:
    instruction = study.root / "seed/AGENTS.md"
    task = study.root / "seed/TASK.md"
    layouts: list[dict[str, Any]] = []
    for index in range(ROLLOUT_COUNT):
        rollout = study.rollout_dir(index)
        state_dir = study.rollout_state(index)
        codex_home = study.codex_home(index)
        rollout.mkdir(parents=True, mode=0o700)
        state_dir.mkdir(parents=True, mode=0o700)
        codex_home.mkdir(mode=0o700)
        shutil.copy2(instruction, rollout / "AGENTS.md", follow_symlinks=False)
        os.chmod(rollout / "AGENTS.md", 0o444)
        os.symlink(study.shared_workspace, rollout / "shared_workspace", target_is_directory=True)
        os.symlink(study.archive, rollout / "archive", target_is_directory=True)
        os.symlink(study.shared_workspace / "TASK.md", rollout / "TASK.md")
        os.symlink(auth_file, codex_home / "auth.json")
        config = render_config(
            study.shared_workspace,
            study.root,
            Path(codex_identity["installation_root"]),
        ).encode("utf-8")
        atomic_write(codex_home / "config.toml", config)
        atomic_json(codex_home / "hooks.json", render_hooks(study.root, state_dir))
        atomic_json(state_dir / "compaction_counter.json", {"count": 0})
        layouts.append(
            {
                "index": index,
                "rollout_dir": str(rollout),
                "rollout_identity": lstat_identity(rollout),
                "state_dir": str(state_dir),
                "state_identity": lstat_identity(state_dir),
                "codex_home": str(codex_home),
                "config_sha256": sha256_file(codex_home / "config.toml"),
                "hooks_sha256": sha256_file(codex_home / "hooks.json"),
                "auth_strategy": "symlink-to-existing-Codex-auth",
                "shared_workspace_resolved": str((rollout / "shared_workspace").resolve()),
                "archive_resolved": str((rollout / "archive").resolve()),
                "task_resolved": str((rollout / "TASK.md").resolve()),
            }
        )
    return layouts


def materialize_shared_task(study: Study) -> None:
    task_bytes = (study.root / "seed/TASK.md").read_bytes()
    atomic_write(study.shared_workspace / "TASK.md", task_bytes, 0o444)


def initialize_study(
    study: Study,
    *,
    auth_home: Path,
    offline_pinned_codex: bool = False,
) -> dict[str, Any]:
    if study.root.resolve(strict=True) != study.root.absolute():
        raise ControlError(f"study root path is not canonical: {study.root}")
    if study.runtime.exists() or study.runtime.is_symlink():
        raise ControlError(f"runtime already exists; refusing to overwrite: {study.runtime}")
    task_identity = seed_task_identity(study.root / "seed/TASK.md")
    auth_file = auth_home.expanduser().resolve(strict=True) / "auth.json"
    if auth_file.is_symlink() or not auth_file.is_file():
        raise ControlError("existing Codex auth.json is unavailable or not a regular file")
    if stat.S_IMODE(auth_file.stat().st_mode) & 0o077:
        raise ControlError("existing Codex auth.json permissions are too broad")
    codex_identity = (
        offline_pinned_executable_identity(
            study.codex_command,
            study.root / "seed/PINS.json",
        )
        if offline_pinned_codex
        else executable_identity(study.codex_command)
    )
    if codex_identity["version"] != EXPECTED_CODEX_VERSION:
        raise ControlError(
            f"expected {EXPECTED_CODEX_VERSION}, got {codex_identity['version']}"
        )
    validate_seed_pins(
        study,
        task_identity=task_identity,
        codex_identity=codex_identity,
    )

    study.runtime.mkdir(mode=0o700)
    study.shared_workspace.mkdir(parents=True, mode=0o700)
    destination = create_initial_empty_repository(study.archive)
    materialize_shared_task(study)
    layouts = prepare_rollout_layout(study, auth_file, codex_identity)
    instruction_hash = sha256_file(study.root / "seed/AGENTS.md")
    state = {
        "format": "base-codex-compaction-control-state",
        "version": 2,
        "control_name": "codex_compaction_shared_git_control",
        "initialized_at": utc_now(),
        "status": "initialized",
        "rollout_count": ROLLOUT_COUNT,
        "completed_iterations": 0,
        "sessions": [None for _ in range(ROLLOUT_COUNT)],
        "compaction_counts": [0 for _ in range(ROLLOUT_COUNT)],
        "archive_identity": destination["identity"],
        "archive_initial_state": destination["empty_repository_identity"],
        "task_sha256": task_identity["sha256"],
        "instruction_sha256": instruction_hash,
        "fresh_prompt_sha256": sha256_bytes(FRESH_PROMPT.encode()),
        "continuation_input_sha256": sha256_bytes(CONTINUATION_INPUT.encode()),
        "config_sha256": layouts[0]["config_sha256"],
        "hooks_sha256_by_rollout": [item["hooks_sha256"] for item in layouts],
        "codex": codex_identity,
    }
    atomic_json(study.study_state_path, state)
    init_manifest = {
        "format": "base-codex-compaction-control-init",
        "version": 2,
        "created_at": utc_now(),
        "control_name": "codex_compaction_shared_git_control",
        "provider_call": False,
        "archive_seed": empty_repository_pin(),
        "destination_archive": str(study.archive),
        "destination": destination,
        "task": task_identity,
        "instruction": {
            "path": str(study.root / "seed/AGENTS.md"),
            "sha256": instruction_hash,
            "bytes": (study.root / "seed/AGENTS.md").stat().st_size,
        },
        "fresh_prompt": {"text": FRESH_PROMPT, "sha256": state["fresh_prompt_sha256"]},
        "continuation_input": {
            "text": CONTINUATION_INPUT,
            "sha256": state["continuation_input_sha256"],
        },
        "codex": codex_identity,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "permissions": "custom control profile: private rollout + shared workspace write, command network disabled",
        "rollouts": layouts,
        "auth": {
            "strategy": "one symlink per private CODEX_HOME to existing auth.json",
            "secret_bytes_copied": False,
            "secret_values_logged": False,
        },
    }
    atomic_json(study.runtime / "manifests/init.json", init_manifest)
    return init_manifest


def verify_layout(study: Study, state: dict[str, Any]) -> dict[str, Any]:
    if state.get("archive_initial_state") != empty_repository_pin():
        raise ControlError("study state does not pin an initially empty unborn archive")
    if study.root.is_symlink() or study.runtime.is_symlink() or study.shared_workspace.is_symlink():
        raise ControlError("study, runtime, and shared workspace must be real directories")
    if study.archive.is_symlink():
        raise ControlError("canonical shared archive path must not be a symlink")
    archive_identity = {
        "root": lstat_identity(study.archive),
        "git_dir": lstat_identity(repository_git_dir(study.archive)),
    }
    expected_identity = state.get("archive_identity")
    if archive_identity != expected_identity:
        raise ControlError("shared archive path or inode identity changed")
    resolved_shared: set[str] = set()
    resolved_archive: set[str] = set()
    rollout_identities: list[dict[str, Any]] = []
    recorded_hooks = state.get("hooks_sha256_by_rollout")
    if not isinstance(recorded_hooks, list) or len(recorded_hooks) != ROLLOUT_COUNT:
        raise ControlError("study state does not pin eight private hook configurations")
    for index in range(ROLLOUT_COUNT):
        rollout = study.rollout_dir(index)
        state_dir = study.rollout_state(index)
        if rollout.is_symlink() or state_dir.is_symlink():
            raise ControlError(f"private rollout/state path was replaced for index {index}")
        if not rollout.is_dir() or not state_dir.is_dir():
            raise ControlError(f"private rollout/state path is missing for index {index}")
        shared_link = rollout / "shared_workspace"
        archive_link = rollout / "archive"
        task_link = rollout / "TASK.md"
        if not shared_link.is_symlink() or not archive_link.is_symlink() or not task_link.is_symlink():
            raise ControlError(f"shared path links changed for rollout {index}")
        resolved_shared.add(str(shared_link.resolve(strict=True)))
        resolved_archive.add(str(archive_link.resolve(strict=True)))
        if task_link.resolve(strict=True) != (study.shared_workspace / "TASK.md").resolve(strict=True):
            raise ControlError(f"TASK.md link changed for rollout {index}")
        if (rollout / "AGENTS.md").read_bytes() != (study.root / "seed/AGENTS.md").read_bytes():
            raise ControlError(f"base instructions changed for rollout {index}")
        rollout_identities.append(
            {
                "index": index,
                "rollout": lstat_identity(rollout),
                "state": lstat_identity(state_dir),
                "codex_home": lstat_identity(study.codex_home(index)),
                "config_sha256": sha256_file(study.codex_home(index) / "config.toml"),
                "hooks_sha256": sha256_file(study.codex_home(index) / "hooks.json"),
            }
        )
        if state.get("config_sha256") != rollout_identities[-1]["config_sha256"]:
            raise ControlError(f"private Codex config changed for rollout {index}")
        expected_hooks_hash = sha256_bytes(
            (
                json.dumps(render_hooks(study.root, state_dir), indent=2, sort_keys=True)
                + "\n"
            ).encode()
        )
        actual_hooks_hash = rollout_identities[-1]["hooks_sha256"]
        if recorded_hooks[index] != actual_hooks_hash:
            raise ControlError(f"recorded private hooks changed for rollout {index}")
        if expected_hooks_hash != actual_hooks_hash:
            raise ControlError(f"private Codex hooks changed for rollout {index}")
    expected_shared = str(study.shared_workspace.resolve(strict=True))
    expected_archive = str(study.archive.resolve(strict=True))
    if resolved_shared != {expected_shared} or resolved_archive != {expected_archive}:
        raise ControlError("the eight rollouts do not share the exact same workspace/archive")
    if git(study.archive, "remote").stdout.strip():
        raise ControlError("shared archive unexpectedly has a configured remote")
    return {
        "archive": archive_identity,
        "shared_workspace_resolved": expected_shared,
        "archive_resolved": expected_archive,
        "rollouts": rollout_identities,
    }


def configured_tool_controls(config_text: str, feature_output: str | None = None) -> dict[str, Any]:
    required = {
        "agents.enabled": re.search(r"(?ms)^\[agents\]\s+enabled\s*=\s*false\s*$", config_text),
        "features.multi_agent": re.search(
            r"(?ms)^\[features\].*?^multi_agent\s*=\s*false\s*$", config_text
        ),
        "features.multi_agent_v2": re.search(
            r"(?ms)^\[features\].*?^multi_agent_v2\s*=\s*false\s*$", config_text
        ),
    }
    missing = sorted(key for key, match in required.items() if match is None)
    if missing:
        raise ControlError(f"multi-agent disabling config is incomplete: {missing}")
    if "mcp_servers." in config_text or "model_instructions_file" in config_text:
        raise ControlError("config contains an MCP server or replacement instruction file")
    feature_status: dict[str, bool] = {}
    if feature_output is not None:
        for line in feature_output.splitlines():
            fields = line.split()
            if len(fields) >= 3 and fields[0] in {"multi_agent", "multi_agent_v2"}:
                feature_status[fields[0]] = fields[-1].lower() == "true"
        if feature_status != {"multi_agent": False, "multi_agent_v2": False}:
            raise ControlError(
                f"effective Codex features did not disable multi-agent: {feature_status}"
            )
    return {
        "agents.enabled": False,
        "features.multi_agent": False,
        "features.multi_agent_v2": False,
        "effective_feature_status": feature_status,
        "forbidden_native_tool_names": sorted(FORBIDDEN_COLLABORATION_TOOLS),
        "mcp_servers_configured": False,
        "replacement_model_instructions_file": False,
    }


def private_cli_environment(study: Study, index: int) -> dict[str, str]:
    environment = study.codex_env(index)
    # Provider authentication is read through the auth.json symlink. Do not pass
    # unrelated environment credentials to Codex or its spawned commands.
    for name in list(environment):
        upper = name.upper()
        if any(marker in upper for marker in ("PASSWORD", "SECRET", "TOKEN", "API_KEY")):
            environment.pop(name, None)
    return environment


def provider_free_sandbox_check(
    study: Study,
    codex_executable: str,
    codex_runtime_root: Path,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="codex-control-sandbox-") as raw:
        root = Path(raw)
        rollout = root / "rollout"
        shared = root / "shared_workspace"
        archive = shared / "archive"
        custom_home = root / "custom-home"
        legacy_home = root / "legacy-home"
        rollout.mkdir()
        shared.mkdir()
        custom_home.mkdir()
        legacy_home.mkdir()
        os.symlink(shared, rollout / "shared_workspace", target_is_directory=True)
        _run(["git", "init", "-b", "main", str(archive)])
        git(archive, "config", "user.name", "control-preflight")
        git(archive, "config", "user.email", "control-preflight@invalid")
        atomic_write(archive / "seed.txt", b"seed\n", 0o644)
        git(archive, "add", "seed.txt")
        git(archive, "commit", "-m", "seed")
        atomic_write(
            custom_home / "config.toml",
            render_config(shared, root, codex_runtime_root).encode("utf-8"),
        )
        atomic_write(
            legacy_home / "config.toml",
            b'approval_policy = "never"\nsandbox_mode = "workspace-write"\n',
        )
        ref = "refs/control-preflight/write-test"
        command = ["git", "-C", str(archive), "update-ref", ref, "HEAD"]
        common = os.environ.copy()
        common["GIT_CEILING_DIRECTORIES"] = str(root)
        custom_env = common | {"CODEX_HOME": str(custom_home)}
        custom = _run(
            [
                codex_executable,
                "sandbox",
                "-P",
                "control",
                "-C",
                str(rollout),
                "--",
                *command,
            ],
            env=custom_env,
            check=False,
        )
        if custom.returncode != 0:
            raise ControlError(
                "custom permission profile cannot write shared Git metadata: "
                + custom.stderr.decode("utf-8", "replace")[:800]
            )
        if git(archive, "rev-parse", "--verify", ref, check=False).returncode != 0:
            raise ControlError("custom permission profile did not create the test ref")
        git(archive, "update-ref", "-d", ref)
        denied_read_results: list[dict[str, Any]] = []
        denied_paths = (
            Path.home() / ".codex/auth.json",
            study.root.parent.parent / "README.md",
        )
        for denied_path in denied_paths:
            denied = _run(
                [
                    codex_executable,
                    "sandbox",
                    "-P",
                    "control",
                    "-C",
                    str(rollout),
                    "--",
                    "/usr/bin/test",
                    "-r",
                    str(denied_path),
                ],
                env=custom_env,
                check=False,
            )
            if denied.returncode == 0:
                raise ControlError(
                    f"custom permission profile can read forbidden path: {denied_path}"
                )
            denied_read_results.append(
                {"path": str(denied_path), "sandbox_exit_status": denied.returncode}
            )
        legacy_env = common | {"CODEX_HOME": str(legacy_home)}
        legacy = _run(
            [codex_executable, "sandbox", "-C", str(rollout), "--", *command],
            env=legacy_env,
            check=False,
        )
        if legacy.returncode == 0:
            raise ControlError(
                "legacy workspace-write unexpectedly wrote protected shared Git metadata"
            )
        return {
            "at": utc_now(),
            "provider_call": False,
            "disposable_repository": True,
            "custom_profile": "control",
            "custom_profile_exit_status": custom.returncode,
            "custom_profile_git_metadata_write": True,
            "legacy_workspace_write_exit_status": legacy.returncode,
            "legacy_workspace_write_git_metadata_write": False,
            "forbidden_path_reads": denied_read_results,
            "selected_as_narrowest_working_stock_permission": True,
        }


def run_preflight(study: Study, *, real_cli: bool = True) -> dict[str, Any]:
    state = load_json(study.study_state_path)
    if not isinstance(state, dict):
        raise ControlError("study state is invalid")
    layout = verify_layout(study, state)
    codex_identity = executable_identity(study.codex_command)
    if codex_identity["version"] != EXPECTED_CODEX_VERSION:
        raise ControlError("installed Codex version no longer matches the pinned version")
    for key in (
        "version",
        "launcher_sha256",
        "native_binary_sha256",
        "installation_root",
    ):
        if key in state.get("codex", {}) and state["codex"][key] != codex_identity.get(key):
            raise ControlError(f"installed Codex identity changed at {key}")
    task_identity = seed_task_identity(study.root / "seed/TASK.md")
    validate_seed_pins(
        study,
        task_identity=task_identity,
        codex_identity=codex_identity,
    )
    if sha256_file(study.root / "seed/TASK.md") != state.get("task_sha256"):
        raise ControlError("seed task bytes changed")
    if sha256_file(study.root / "seed/AGENTS.md") != state.get("instruction_sha256"):
        raise ControlError("seed additive instructions changed")
    initial_archive_verification: dict[str, Any] | None = None
    if (
        state.get("completed_iterations") == 0
        and state.get("sessions") == [None for _ in range(ROLLOUT_COUNT)]
        and state.get("compaction_counts") == [0 for _ in range(ROLLOUT_COUNT)]
    ):
        initial_archive_verification = verify_initial_empty_repository(study.archive)
    config_path = study.codex_home(0) / "config.toml"
    config_text = config_path.read_text(encoding="utf-8")
    environment = private_cli_environment(study, 0)
    feature_result = _run(
        [study.codex_command, "features", "list"],
        cwd=study.rollout_dir(0),
        env=environment,
    )
    feature_text = feature_result.stdout.decode("utf-8", "replace")
    tool_controls = configured_tool_controls(config_text, feature_text)
    prompt_result = _run(
        [study.codex_command, "debug", "prompt-input", FRESH_PROMPT],
        cwd=study.rollout_dir(0),
        env=environment,
    )
    prompt_bytes = prompt_result.stdout
    instruction = (study.root / "seed/AGENTS.md").read_bytes()
    try:
        rendered_prompt = json.loads(prompt_bytes)
    except json.JSONDecodeError as exc:
        raise ControlError(f"provider-free prompt rendering was not JSON: {exc}") from None
    rendered_text_parts: list[str] = []
    pending_prompt: list[Any] = [rendered_prompt]
    while pending_prompt:
        value = pending_prompt.pop()
        if isinstance(value, str):
            rendered_text_parts.append(value)
        elif isinstance(value, dict):
            pending_prompt.extend(value.values())
        elif isinstance(value, list):
            pending_prompt.extend(value)
    rendered_text = "\n".join(rendered_text_parts)
    if instruction.decode("utf-8") not in rendered_text or FRESH_PROMPT not in rendered_text:
        raise ControlError("provider-free prompt rendering omitted base instructions or Begin.")
    model_catalog_result = _run(
        [study.codex_command, "debug", "models", "--bundled"],
        cwd=study.rollout_dir(0),
        env=environment,
    )
    model_catalog = json.loads(model_catalog_result.stdout)
    model_record: dict[str, Any] | None = None
    pending: list[Any] = [model_catalog]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if value.get("slug") == MODEL:
                model_record = value
                break
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    if model_record is None:
        raise ControlError(f"installed Codex model catalog does not contain {MODEL}")
    if REASONING_EFFORT not in {
        item.get("effort")
        for item in model_record.get("supported_reasoning_levels", [])
        if isinstance(item, dict)
    }:
        raise ControlError("pinned reasoning effort is unsupported")
    base_instructions = model_record.get("base_instructions")
    if not isinstance(base_instructions, str):
        raise ControlError("model catalog did not expose stock base instructions")
    sandbox = provider_free_sandbox_check(
        study,
        str(Path(shutil.which(study.codex_command) or study.codex_command)),
        Path(codex_identity["installation_root"]),
    ) if real_cli else {"provider_call": False, "skipped_for_fake": True}
    preflight = {
        "format": "base-codex-compaction-control-preflight",
        "version": 2,
        "at": utc_now(),
        "provider_call": False,
        "layout": layout,
        "initial_empty_archive": initial_archive_verification,
        "codex": codex_identity,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "stock_base_instructions_sha256": sha256_bytes(base_instructions.encode()),
        "additive_instruction_sha256": sha256_bytes(instruction),
        "rendered_prompt_input_sha256": sha256_bytes(prompt_bytes),
        "fresh_prompt_sha256": sha256_bytes(FRESH_PROMPT.encode()),
        "config_sha256": sha256_file(config_path),
        "tool_controls": tool_controls,
        "sandbox": sandbox,
    }
    preflight_dir = study.runtime / "preflight"
    atomic_write(preflight_dir / "prompt-input.json", prompt_bytes)
    atomic_write(preflight_dir / "features.txt", feature_result.stdout)
    atomic_json(preflight_dir / "latest.json", preflight)
    return preflight


def shared_non_archive_entries(study: Study) -> list[str]:
    return sorted(entry.name for entry in study.shared_workspace.iterdir() if entry.name != "archive")


def safe_remove_entry(entry: Path, shared_workspace: Path) -> None:
    if entry.parent != shared_workspace or entry.name in {"", ".", "..", "archive"}:
        raise ControlError(f"unsafe shared cleanup target: {entry}")
    info = entry.lstat()
    if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
        shutil.rmtree(entry)
    else:
        entry.unlink()


def clean_shared_workspace(study: Study, expected_archive_identity: dict[str, Any]) -> dict[str, Any]:
    shared = ensure_real_directory(study.shared_workspace, "shared workspace")
    archive = study.archive
    if archive.parent != shared or archive.name != "archive" or archive.is_symlink():
        raise ControlError("archive cleanup target is not canonical")
    current_identity = {
        "root": lstat_identity(archive),
        "git_dir": lstat_identity(repository_git_dir(archive)),
    }
    if current_identity != expected_archive_identity:
        raise ControlError("archive path/inode identity changed before cleanup")
    locks = git_lock_paths(archive)
    if locks:
        raise ControlError(f"archive cleanup found Git lock files: {locks}")
    before = git_snapshot(archive)
    refs_before = git_refs_bytes(archive)
    operation = before["operation_state"]
    if operation in {"rebase", "am", "cherry-pick", "revert"}:
        quit_commands = {
            "rebase": ("rebase", "--quit"),
            "am": ("am", "--quit"),
            "cherry-pick": ("cherry-pick", "--quit"),
            "revert": ("revert", "--quit"),
        }
        git(archive, *quit_commands[operation])
        if git_operation_state(archive) is not None:
            raise ControlError("could not clear known Git integration operation")
    elif operation not in {None, "merge"}:
        raise ControlError(f"unsupported Git operation state: {operation}")
    if before["head"] is None:
        git(archive, "read-tree", "--empty")
        cleanup_mode = "unborn-read-tree-empty"
    else:
        git(archive, "reset", "--hard", "HEAD")
        cleanup_mode = "committed-reset-hard-head"
    git(archive, "clean", "-ffdx")
    if git_operation_state(archive) is not None:
        raise ControlError("Git cleanup left an integration operation active")
    after = git_snapshot(archive)
    if after["status"]:
        raise ControlError("Git cleanup left dirty or ignored archive state")
    if (
        after["head"] != before["head"]
        or after["branch"] != before["branch"]
        or git_refs_bytes(archive) != refs_before
    ):
        raise ControlError("Git cleanup changed HEAD, current branch, or refs")
    removed_entries = shared_non_archive_entries(study)
    for name in removed_entries:
        safe_remove_entry(shared / name, shared)
    if shared_non_archive_entries(study):
        raise ControlError("batch-local shared workspace cleanup was incomplete")
    final_identity = {
        "root": lstat_identity(archive),
        "git_dir": lstat_identity(repository_git_dir(archive)),
    }
    if final_identity != expected_archive_identity:
        raise ControlError("archive identity changed during cleanup")
    return {
        "at": utc_now(),
        "cleanup_mode": cleanup_mode,
        "operation_state_cleared": operation,
        "discarded_archive_status_entry_count": len(before["status"]),
        "removed_shared_entries": removed_entries,
        "before": before,
        "after": after,
    }


def _walk_secret_strings(value: Any, sensitive: bool = False) -> Iterable[bytes]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_sensitive = sensitive or any(
                marker in str(key).lower()
                for marker in ("token", "secret", "password", "credential", "auth", "key")
            )
            yield from _walk_secret_strings(child, child_sensitive)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_secret_strings(child, sensitive)
    elif sensitive and isinstance(value, str) and len(value.encode("utf-8")) >= 8:
        yield value.encode("utf-8")


class EvidenceRedactor:
    token_patterns = (
        re.compile(rb"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        re.compile(rb"\bsk-[A-Za-z0-9_-]{8,}"),
    )

    def __init__(self, auth_file: Path, environment: dict[str, str] | None = None):
        values: set[bytes] = set()
        try:
            auth = json.loads(auth_file.read_text(encoding="utf-8"))
            values.update(_walk_secret_strings(auth))
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        for name, value in (environment or os.environ).items():
            if any(
                marker in name.upper()
                for marker in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "CREDENTIAL")
            ) and len(value.encode("utf-8")) >= 8:
                values.add(value.encode("utf-8"))
        self.values = sorted(values, key=len, reverse=True)

    def redact(self, data: bytes) -> tuple[bytes, int]:
        output = data
        replacements = 0
        for secret in self.values:
            count = output.count(secret)
            if count:
                output = output.replace(secret, b"[REDACTED_SECRET]")
                replacements += count
        for pattern in self.token_patterns:
            output, count = pattern.subn(b"[REDACTED_SECRET]", output)
            replacements += count
        return output, replacements


def parse_jsonl_evidence(data: bytes) -> dict[str, Any]:
    session_ids: list[str] = []
    final_messages: list[str] = []
    errors: list[str] = []
    inventory_tools: set[str] = set()
    invalid_lines = 0

    def inspect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"tools", "tool_names", "available_tools"} and isinstance(child, list):
                    for item in child:
                        if isinstance(item, str):
                            inventory_tools.add(item)
                        elif isinstance(item, dict) and isinstance(item.get("name"), str):
                            inventory_tools.add(item["name"])
                if key == "tool_name" and isinstance(child, str):
                    inventory_tools.add(child)
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)

    for raw_line in data.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            invalid_lines += 1
            continue
        if not isinstance(event, dict):
            continue
        inspect(event)
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            session_ids.append(event["thread_id"])
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            final_messages.append(item["text"])
        if event.get("type") in {"error", "turn.failed"}:
            errors.append(json.dumps(event, sort_keys=True)[:2000])
    forbidden = sorted(inventory_tools & FORBIDDEN_COLLABORATION_TOOLS)
    return {
        "session_ids": session_ids,
        "final_message": final_messages[-1] if final_messages else None,
        "agent_message_count": len(final_messages),
        "errors": errors,
        "invalid_jsonl_line_count": invalid_lines,
        "emitted_or_used_tool_names": sorted(inventory_tools),
        "forbidden_collaboration_tools": forbidden,
    }


def read_compaction_count(state_dir: Path) -> int:
    value = load_json(state_dir / "compaction_counter.json")
    count = value.get("count") if isinstance(value, dict) else None
    if not isinstance(count, int) or count < 0:
        raise ControlError(f"invalid compaction count in {state_dir}")
    return count


def build_codex_command(
    study: Study,
    index: int,
    *,
    resume: bool,
    session_id: str | None,
) -> tuple[list[str], str]:
    common = [
        "--json",
        "--strict-config",
        "--ignore-rules",
        "--dangerously-bypass-hook-trust",
        "--skip-git-repo-check",
        "-m",
        MODEL,
        "-c",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "-c",
        "agents.enabled=false",
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
    ]
    if resume:
        if session_id is None:
            raise ControlError(f"rollout {index} has no session id to resume")
        prompt = CONTINUATION_INPUT
        return [study.codex_command, "exec", "resume", *common, session_id, prompt], prompt
    prompt = FRESH_PROMPT
    return [study.codex_command, "exec", *common, prompt], prompt


def process_result(
    *,
    study: Study,
    index: int,
    process: subprocess.Popen[bytes],
    command: list[str],
    prompt: str,
    started_at: str,
    started_monotonic: float,
    evidence_dir: Path,
    redactor: EvidenceRedactor,
) -> dict[str, Any]:
    stdout_raw, stderr_raw = process.communicate()
    ended_monotonic = time.monotonic()
    ended_at = utc_now()
    stdout, stdout_redactions = redactor.redact(stdout_raw)
    stderr, stderr_redactions = redactor.redact(stderr_raw)
    atomic_write(evidence_dir / "events.jsonl", stdout)
    atomic_write(evidence_dir / "stderr.log", stderr)
    parsed = parse_jsonl_evidence(stdout)
    final_message = parsed["final_message"]
    if final_message is not None:
        atomic_write(
            evidence_dir / "final_message.txt",
            (final_message + ("" if final_message.endswith("\n") else "\n")).encode(),
        )
    return {
        "rollout_index": index,
        "command": command,
        "prompt": prompt,
        "prompt_sha256": sha256_bytes(prompt.encode()),
        "cwd": str(study.rollout_dir(index)),
        "codex_home": str(study.codex_home(index)),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": round(ended_monotonic - started_monotonic, 6),
        "pid": process.pid,
        "exit_status": process.returncode,
        "stdout": {
            "path": str(evidence_dir / "events.jsonl"),
            "sha256": sha256_bytes(stdout),
            "emitted_sha256_before_redaction": sha256_bytes(stdout_raw),
            "bytes": len(stdout),
            "redaction_count": stdout_redactions,
            "exact_as_emitted": stdout_redactions == 0,
        },
        "stderr": {
            "path": str(evidence_dir / "stderr.log"),
            "sha256": sha256_bytes(stderr),
            "emitted_sha256_before_redaction": sha256_bytes(stderr_raw),
            "bytes": len(stderr),
            "redaction_count": stderr_redactions,
            "exact_as_emitted": stderr_redactions == 0,
        },
        "stream": parsed,
    }


class LauncherLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> "LauncherLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stream.close()
            raise ControlError("another launcher process holds the study lock") from None
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.stream is not None:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()


def run_iteration(
    study: Study,
    *,
    resume: bool,
    preflight: bool = True,
    real_cli: bool = True,
) -> dict[str, Any]:
    with LauncherLock(study.runtime / "launcher.lock"):
        state = load_json(study.study_state_path)
        if not isinstance(state, dict) or state.get("rollout_count") != ROLLOUT_COUNT:
            raise ControlError("study state is invalid")
        if state.get("status") not in {"initialized", "ready"}:
            raise ControlError(
                f"study is not runnable after status {state.get('status')!r}; inspect the last manifest"
            )
        completed = state.get("completed_iterations")
        sessions = state.get("sessions")
        recorded_counts = state.get("compaction_counts")
        if not isinstance(completed, int) or not isinstance(sessions, list) or not isinstance(
            recorded_counts, list
        ):
            raise ControlError("study state fields are invalid")
        if len(sessions) != ROLLOUT_COUNT or len(recorded_counts) != ROLLOUT_COUNT:
            raise ControlError("study state does not describe exactly eight rollouts")
        if resume:
            if completed < 1 or not all(isinstance(item, str) for item in sessions):
                raise ControlError("resume-next-iteration requires eight completed persistent sessions")
        else:
            if completed != 0 or any(item is not None for item in sessions):
                raise ControlError("run-one-iteration is only valid for eight fresh sessions")
            verify_initial_empty_repository(study.archive)

        materialize_shared_task(study)
        layout_before = verify_layout(study, state)
        actual_counts = [read_compaction_count(study.rollout_state(i)) for i in range(ROLLOUT_COUNT)]
        if actual_counts != recorded_counts:
            raise ControlError("durable hook counters do not match the study state")
        archive_before = git_snapshot(study.archive)
        if (
            archive_before["status"]
            or archive_before["operation_state"] is not None
            or archive_before["locks"]
        ):
            raise ControlError("archive is not in a clean runnable pre-batch state")
        preflight_record = run_preflight(study, real_cli=real_cli) if preflight else None
        iteration_index = completed + 1
        iteration_dir = study.runtime / "iterations" / f"iteration_{iteration_index:06d}"
        if iteration_dir.exists() or iteration_dir.is_symlink():
            raise ControlError(f"iteration evidence already exists: {iteration_dir}")
        iteration_dir.mkdir(parents=True, mode=0o700)

        targets = [count + 1 for count in actual_counts]
        for index, target in enumerate(targets):
            atomic_json(
                study.rollout_state(index) / "boundary.json",
                {
                    "iteration_index": iteration_index,
                    "starting_count": actual_counts[index],
                    "target_count": target,
                    "continuation_input": CONTINUATION_INPUT,
                    "continuation_input_sha256": sha256_bytes(CONTINUATION_INPUT.encode()),
                    "configured_at": utc_now(),
                },
            )

        manifest_path = iteration_dir / "manifest.json"
        running_manifest: dict[str, Any] = {
            "format": "base-codex-compaction-control-iteration",
            "version": 2,
            "control_name": "codex_compaction_shared_git_control",
            "iteration_index": iteration_index,
            "mode": "resume" if resume else "fresh",
            "status": "running",
            "started_at": utc_now(),
            "rollout_count": ROLLOUT_COUNT,
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "permissions": "control",
            "fresh_prompt": FRESH_PROMPT if not resume else None,
            "continuation_input": CONTINUATION_INPUT,
            "task_sha256": state["task_sha256"],
            "instruction_sha256": state["instruction_sha256"],
            "codex": executable_identity(study.codex_command),
            "layout_before": layout_before,
            "archive_before": archive_before,
            "compaction_counts_before": actual_counts,
            "compaction_targets": targets,
            "preflight": preflight_record,
            "rollouts": [],
        }
        atomic_json(manifest_path, running_manifest)

        processes: list[tuple[int, subprocess.Popen[bytes], list[str], str, str, float, EvidenceRedactor]] = []
        launch_error: str | None = None
        try:
            for index in range(ROLLOUT_COUNT):
                command, prompt = build_codex_command(
                    study,
                    index,
                    resume=resume,
                    session_id=sessions[index] if isinstance(sessions[index], str) else None,
                )
                evidence_dir = iteration_dir / rollout_name(index)
                evidence_dir.mkdir(mode=0o700)
                environment = private_cli_environment(study, index)
                redactor = EvidenceRedactor(
                    study.codex_home(index) / "auth.json", os.environ.copy()
                )
                started_at = utc_now()
                started_monotonic = time.monotonic()
                process = subprocess.Popen(
                    command,
                    cwd=study.rollout_dir(index),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                processes.append(
                    (
                        index,
                        process,
                        command,
                        prompt,
                        started_at,
                        started_monotonic,
                        redactor,
                    )
                )
        except Exception as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
            for _, process, *_ in processes:
                if process.poll() is None:
                    process.terminate()

        rollout_results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=ROLLOUT_COUNT) as pool:
            futures = []
            for index, process, command, prompt, started_at, started_mono, redactor in processes:
                futures.append(
                    pool.submit(
                        process_result,
                        study=study,
                        index=index,
                        process=process,
                        command=command,
                        prompt=prompt,
                        started_at=started_at,
                        started_monotonic=started_mono,
                        evidence_dir=iteration_dir / rollout_name(index),
                        redactor=redactor,
                    )
                )
            for future in concurrent.futures.as_completed(futures):
                rollout_results.append(future.result())
        rollout_results.sort(key=lambda item: item["rollout_index"])

        counts_after = [read_compaction_count(study.rollout_state(i)) for i in range(ROLLOUT_COUNT)]
        captured_sessions = list(sessions)
        barrier_failures: list[str] = []
        if launch_error is not None:
            barrier_failures.append(f"launch error: {launch_error}")
        if len(rollout_results) != ROLLOUT_COUNT:
            barrier_failures.append(
                f"only {len(rollout_results)} of {ROLLOUT_COUNT} processes were launched"
            )
        for result in rollout_results:
            index = result["rollout_index"]
            emitted_sessions = result["stream"]["session_ids"]
            if not emitted_sessions:
                barrier_failures.append(f"rollout {index} emitted no session id")
            else:
                current_session = emitted_sessions[0]
                if resume and current_session != sessions[index]:
                    barrier_failures.append(f"rollout {index} resumed a different session id")
                captured_sessions[index] = current_session
            if result["stream"]["forbidden_collaboration_tools"]:
                barrier_failures.append(
                    f"rollout {index} exposed forbidden collaboration tools: "
                    f"{result['stream']['forbidden_collaboration_tools']}"
                )
            if counts_after[index] != targets[index]:
                barrier_failures.append(
                    f"rollout {index} count {counts_after[index]} did not advance exactly to {targets[index]}"
                )
        if len({item for item in captured_sessions if isinstance(item, str)}) != ROLLOUT_COUNT:
            barrier_failures.append("the study does not have exactly eight distinct session ids")
        try:
            layout_after_processes = verify_layout(study, state)
        except ControlError as exc:
            layout_after_processes = {"error": str(exc)}
            barrier_failures.append(str(exc))

        archive_after_processes: dict[str, Any] | None = None
        cleanup: dict[str, Any] | None = None
        cleanup_error: str | None = None
        if not barrier_failures:
            try:
                archive_after_processes = git_snapshot(study.archive)
                cleanup = clean_shared_workspace(
                    study, state["archive_identity"]
                )
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"

        manifest = running_manifest | {
            "ended_at": utc_now(),
            "rollouts": rollout_results,
            "session_ids": captured_sessions,
            "compaction_counts_after": counts_after,
            "barrier_reached": not barrier_failures,
            "barrier_failures": barrier_failures,
            "layout_after_processes": layout_after_processes,
            "archive_after_processes": archive_after_processes,
            "cleanup": cleanup,
            "cleanup_error": cleanup_error,
        }
        if barrier_failures:
            manifest["status"] = "incomplete"
            state["status"] = "blocked_incomplete"
            state["sessions"] = captured_sessions
            state["compaction_counts"] = counts_after
            state["last_iteration_manifest"] = str(manifest_path)
            atomic_json(study.study_state_path, state)
            atomic_json(manifest_path, manifest)
            raise ControlError(
                "iteration incomplete; no relaunch and no cleanup were performed: "
                + "; ".join(barrier_failures)
            )
        if cleanup_error is not None:
            manifest["status"] = "cleanup_failed"
            state["status"] = "cleanup_failed"
            state["sessions"] = captured_sessions
            state["compaction_counts"] = counts_after
            state["last_iteration_manifest"] = str(manifest_path)
            atomic_json(study.study_state_path, state)
            atomic_json(manifest_path, manifest)
            raise ControlError(
                f"all rollouts reached the boundary, but cleanup failed closed: {cleanup_error}"
            )
        manifest["status"] = "complete"
        state["status"] = "ready"
        state["completed_iterations"] = iteration_index
        state["sessions"] = captured_sessions
        state["compaction_counts"] = counts_after
        state["last_iteration_manifest"] = str(manifest_path)
        state["last_completed_at"] = manifest["ended_at"]
        atomic_json(study.study_state_path, state)
        atomic_json(manifest_path, manifest)
        return manifest


def status_record(study: Study) -> dict[str, Any]:
    state = load_json(study.study_state_path)
    if not isinstance(state, dict):
        raise ControlError("study state is invalid")
    archive = git_snapshot(study.archive)
    counts = [read_compaction_count(study.rollout_state(i)) for i in range(ROLLOUT_COUNT)]
    return {
        "control_name": "codex_compaction_shared_git_control",
        "root": str(study.root),
        "state": state,
        "durable_compaction_counts": counts,
        "archive": archive,
        "shared_non_archive_entries": shared_non_archive_entries(study),
        "provider_call": False,
    }


def command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone eight-session stock-Codex automatic-compaction control"
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent, help=argparse.SUPPRESS
    )
    parser.add_argument("--codex", default="codex", help="stock Codex executable")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser(
        "init", help="prepare an empty shared archive and eight private sessions"
    )
    init.add_argument("--auth-home", type=Path, default=Path.home() / ".codex")
    init.add_argument(
        "--offline-pinned-codex",
        action="store_true",
        help="hash-verify the pinned stock executable without launching it",
    )
    subparsers.add_parser("status", help="show local control state without a provider call")
    subparsers.add_parser("preflight", help="run provider-free config, prompt, and sandbox checks")
    subparsers.add_parser("run-one-iteration", help="start iteration 1 with eight fresh sessions")
    subparsers.add_parser("resume-next-iteration", help="resume all eight sessions for one boundary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = command_parser().parse_args(argv)
    study = Study(args.root.absolute(), args.codex)
    try:
        if args.command == "init":
            result = initialize_study(
                study,
                auth_home=args.auth_home,
                offline_pinned_codex=args.offline_pinned_codex,
            )
        elif args.command == "status":
            result = status_record(study)
        elif args.command == "preflight":
            result = run_preflight(study)
        elif args.command == "run-one-iteration":
            result = run_iteration(study, resume=False)
        elif args.command == "resume-next-iteration":
            result = run_iteration(study, resume=True)
        else:
            raise AssertionError(args.command)
    except ControlError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Source and artifact provenance for locally built Codex runner/host pairs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REBUILD = "Rebuild the matching runner/host bundle with --codex-build-runner."
SCHEMA_VERSION = 1


def manifest_path(runner: Path) -> Path:
    return runner.with_name(runner.name + ".bundle.json")


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
    ).stdout


def _source_digest(root: Path, paths: set[Path], target_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        # Git excludes ignored build products; also exclude an explicitly configured
        # target directory even when its name is not covered by .gitignore.
        if path.is_relative_to(target_dir):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            header = [relative, "missing"]
            content_digest = ""
        else:
            if not path.is_file():
                raise RuntimeError(f"Unsupported Codex source input: {path}")
            header = [relative, stat.S_IMODE(mode)]
            if path.is_symlink():
                header.append(os.readlink(path))
            content = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    content.update(chunk)
            content_digest = content.hexdigest()
        digest.update(json.dumps([header, content_digest]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def source_fingerprint(
    project_root: Path, codex_root: Path, runner_crate: Path, target_dir: Path
) -> dict[str, str]:
    """Hash source bytes, including tracked edits/deletions and nonignored additions.

    The outer repository HEAD is deliberately irrelevant: unrelated experiment
    commits do not invalidate this bundle. Codex HEAD is always part of its identity.
    """
    try:
        target_dir = target_dir.resolve()
        if any(root.is_relative_to(target_dir) for root in (runner_crate, codex_root)):
            raise RuntimeError("CARGO_TARGET_DIR must not contain a Codex bundle source tree.")
        roots = {
            "runner": (project_root, [
                runner_crate.relative_to(project_root).as_posix(),
                "utils/codex_runner.py",
                "utils/codex_bundle.py",
            ]),
            "codex": (codex_root, []),
        }
        result = {"codex_head": _git(codex_root, "rev-parse", "HEAD").decode().strip()}
        for label, (root, selectors) in roots.items():
            tracked = _git(root, "ls-files", "--cached", "-z", "--", *selectors)
            paths = {root / os.fsdecode(name) for name in tracked.split(b"\0") if name}
            if any(path.is_relative_to(target_dir) for path in paths):
                raise RuntimeError("CARGO_TARGET_DIR overlaps tracked Codex bundle sources.")
            added = _git(
                root, "ls-files", "--others", "--exclude-standard", "-z", "--", *selectors
            )
            paths.update(root / os.fsdecode(name) for name in added.split(b"\0") if name)
            # Include local Cargo configuration even if an ignore rule hides it.
            config_roots = [root]
            if label == "runner":
                config_roots.append(runner_crate)
            else:
                config_roots.append(codex_root / "codex-rs")
            for config_root in config_roots:
                paths.update(config_root / ".cargo" / name for name in ("config", "config.toml"))
            result[label] = _source_digest(root, paths, target_dir)
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Cannot fingerprint Codex bundle sources. {REBUILD}") from exc


def artifact_identity(path: Path) -> dict[str, int]:
    """Bind a local artifact without reading/hashing build outputs.

    Include ctime and file identity so replacement or same-size writes preserving
    mtime invalidate the pair. This is local freshness metadata, not a portable
    artifact signature or protection against deliberate metadata forgery.
    """
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise RuntimeError(f"Codex bundle artifact is not executable: {path}. {REBUILD}")
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
        "mode": info.st_mode,
    }


def write_manifest(runner: Path, host: Path, sources: dict[str, str], *, release: bool) -> None:
    """Publish only after the caller successfully builds both artifacts."""
    data = {
        "schema": SCHEMA_VERSION,
        "release": release,
        "sources": sources,
        "artifacts": {"runner": artifact_identity(runner), "host": artifact_identity(host)},
    }
    destination = manifest_path(runner)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=destination.name + ".", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_manifest(
    runner: Path, host: Path, sources: dict[str, str], *, release: bool
) -> None:
    try:
        path = manifest_path(runner)
        raw = path.read_bytes()
        data: Any = json.loads(raw)
        expected = {
            "schema": SCHEMA_VERSION,
            "release": release,
            "sources": sources,
            "artifacts": {"runner": artifact_identity(runner), "host": artifact_identity(host)},
        }
        if data != expected or path.read_bytes() != raw:
            raise ValueError("source, profile, or executable identity changed")
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Codex runner/host bundle is stale or has no valid build manifest: {runner}. {REBUILD}"
        ) from exc

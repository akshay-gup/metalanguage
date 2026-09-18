"""Seed new rollout artifact directories with an empty ``AGENTS.md``.

This is deliberately scoped to explicitly supplied rollout artifact roots.  It
does not observe arbitrary host filesystem activity.  Inotify reports a
directory after its creation, so this enforces prompt seeding and end-of-run
coverage, not syscall-level ordering inside one compound shell command.
"""

from __future__ import annotations

import ctypes
import errno
import os
import select
import struct
import sys
import threading
from collections.abc import Iterable
from pathlib import Path


AGENTS_FILENAME = "AGENTS.md"

_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_IN_ONLYDIR = 0x01000000
_IN_DONT_FOLLOW = 0x02000000
_IN_ISDIR = 0x40000000
_WATCH_MASK = (
    _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_ONLYDIR
    | _IN_DONT_FOLLOW
)
_EVENT = struct.Struct("iIII")


def ensure_directory_agents_file(directory: Path) -> bool:
    """Create an empty AGENTS.md in *directory* iff that name is absent."""

    directory_fd = os.open(
        directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        try:
            agents_fd = os.open(
                AGENTS_FILENAME,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | os.O_NOFOLLOW,
                0o644,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            return False
        else:
            os.close(agents_fd)
            return True
    finally:
        os.close(directory_fd)


def ensure_directory_tree_agents_files(root: Path) -> None:
    """Seed every real directory at or below *root* without following symlinks."""

    pending = [root]
    while pending:
        directory = pending.pop()
        if directory.is_symlink() or directory.name == ".git":
            continue
        ensure_directory_agents_file(directory)
        with os.scandir(directory) as entries:
            pending.extend(
                Path(entry.path)
                for entry in entries
                if entry.name != ".git" and entry.is_dir(follow_symlinks=False)
            )


class DirectoryAgentsWatcher:
    """Watch rollout roots and seed directories created while the watcher runs."""

    def __init__(self, roots: Iterable[Path]) -> None:
        self._roots = self._normalize_roots(roots)
        self._fd: int | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._watch_paths: dict[int, Path] = {}
        self._baseline: dict[Path, tuple[int, int]] = {}
        self._libc: ctypes.CDLL | None = None

    @staticmethod
    def _normalize_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
        normalized: list[Path] = []
        for raw_root in roots:
            root = raw_root.expanduser().resolve(strict=True)
            if raw_root.is_symlink() or not root.is_dir():
                raise ValueError(f"directory-agent root is not a real directory: {raw_root}")
            if any(
                root == existing or root.is_relative_to(existing)
                for existing in normalized
            ):
                continue
            normalized = [
                existing for existing in normalized if not existing.is_relative_to(root)
            ]
            normalized.append(root)
        return tuple(normalized)

    def __enter__(self) -> DirectoryAgentsWatcher:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._fd is not None:
            raise RuntimeError("directory-agent watcher is already running")
        if sys.platform != "linux":
            raise RuntimeError("directory-agent watching currently requires Linux inotify")

        libc = ctypes.CDLL(None, use_errno=True)
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_add_watch.restype = ctypes.c_int
        fd = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        if fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))

        self._libc = libc
        self._fd = fd
        try:
            for root in self._roots:
                self._watch_tree(root, baseline=True, seed=True)
            self._thread = threading.Thread(
                target=self._run,
                name="rollout-directory-agents",
                daemon=True,
            )
            self._thread.start()
        except BaseException:
            os.close(fd)
            self._fd = None
            self._libc = None
            raise

    def stop(self) -> None:
        if self._fd is None:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                self._error = self._error or RuntimeError(
                    "directory-agent watcher did not stop"
                )
        try:
            if self._error is None:
                self._reconcile_created_directories()
        finally:
            os.close(self._fd)
            self._fd = None
            self._libc = None
        if self._error is not None:
            raise RuntimeError("directory-agent watcher failed") from self._error

    def _run(self) -> None:
        assert self._fd is not None
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([self._fd], [], [], 0.1)
                if not ready:
                    continue
                try:
                    payload = os.read(self._fd, 64 * 1024)
                except BlockingIOError:
                    continue
                self._consume(payload)
        except BaseException as exc:
            self._error = exc
            self._stop.set()

    def _consume(self, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            if len(payload) - offset < _EVENT.size:
                raise RuntimeError("truncated inotify event")
            watch, mask, _cookie, name_length = _EVENT.unpack_from(payload, offset)
            offset += _EVENT.size
            name_end = offset + name_length
            if name_end > len(payload):
                raise RuntimeError("truncated inotify event name")
            raw_name = payload[offset:name_end].split(b"\0", 1)[0]
            offset = name_end

            if mask & _IN_Q_OVERFLOW:
                raise RuntimeError("inotify queue overflow")
            if mask & _IN_IGNORED:
                self._watch_paths.pop(watch, None)
                continue
            parent = self._watch_paths.get(watch)
            if parent is None:
                continue
            if mask & _IN_DELETE_SELF:
                self._watch_paths.pop(watch, None)
                continue
            if not raw_name or not mask & _IN_ISDIR:
                continue
            if mask & (_IN_CREATE | _IN_MOVED_TO):
                directory = parent / os.fsdecode(raw_name)
                try:
                    self._watch_tree(directory, baseline=False, seed=True)
                except FileNotFoundError:
                    pass

    def _watch_tree(self, directory: Path, *, baseline: bool, seed: bool) -> None:
        if directory.is_symlink():
            return
        directory = directory.resolve(strict=True)
        if not self._is_managed(directory):
            return
        if seed:
            ensure_directory_agents_file(directory)
        identity = self._directory_identity(directory)
        if baseline:
            self._baseline[directory] = identity
        self._add_watch(directory)
        with os.scandir(directory) as entries:
            children = [
                Path(entry.path)
                for entry in entries
                if entry.is_dir(follow_symlinks=False)
            ]
        for child in children:
            try:
                self._watch_tree(child, baseline=baseline, seed=seed)
            except FileNotFoundError:
                continue

    def _add_watch(self, directory: Path) -> None:
        assert self._fd is not None
        assert self._libc is not None
        watch = self._libc.inotify_add_watch(
            self._fd,
            os.fsencode(directory),
            _WATCH_MASK,
        )
        if watch < 0:
            error = ctypes.get_errno()
            if error in {errno.ENOENT, errno.ENOTDIR}:
                raise FileNotFoundError(error, os.strerror(error), directory)
            raise OSError(error, os.strerror(error), directory)
        self._watch_paths[watch] = directory

    def _reconcile_created_directories(self) -> None:
        for root in self._roots:
            self._reconcile_tree(root)

    def _reconcile_tree(self, directory: Path) -> None:
        try:
            if directory.is_symlink():
                return
            directory = directory.resolve(strict=True)
            if not self._is_managed(directory):
                return
            identity = self._directory_identity(directory)
            if self._baseline.get(directory) != identity:
                ensure_directory_agents_file(directory)
            with os.scandir(directory) as entries:
                children = [
                    Path(entry.path)
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False)
                ]
        except FileNotFoundError:
            return
        for child in children:
            self._reconcile_tree(child)

    def _is_managed(self, path: Path) -> bool:
        for root in self._roots:
            if path == root:
                return True
            if path.is_relative_to(root):
                return ".git" not in path.relative_to(root).parts
        return False

    @staticmethod
    def _directory_identity(path: Path) -> tuple[int, int]:
        status = path.stat(follow_symlinks=False)
        return status.st_dev, status.st_ino

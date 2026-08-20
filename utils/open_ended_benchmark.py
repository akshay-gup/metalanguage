"""Unevaluated lifecycle for a human-authored open-ended task."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.benchmark_driver import BenchmarkOutcome, PreparedBatch, RolloutBenchmark


TASK_RECORD_FORMAT = "metalanguage-open-ended-task"
TASK_RECORD_VERSION = 1
TASK_CONTENT_FILENAME = "task.md"
TASK_METADATA_FILENAME = "task.json"


@dataclass(frozen=True)
class OpenEndedTask:
    content: bytes = field(repr=False)
    sha256: str
    source_path: str | None = None


@dataclass(frozen=True)
class OpenEndedConfig:
    task: OpenEndedTask
    state_dir: Path


def _validated_task(content: bytes, source_path: str | None) -> OpenEndedTask:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("open-ended task content must be valid UTF-8 Markdown") from None
    if not text.strip():
        raise ValueError("open-ended task content must not be blank")
    return OpenEndedTask(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        source_path=source_path,
    )


def _load_persisted_task(state_dir: Path) -> OpenEndedTask | None:
    content_path = state_dir / TASK_CONTENT_FILENAME
    metadata_path = state_dir / TASK_METADATA_FILENAME
    if not content_path.exists() and not metadata_path.exists():
        return None
    if not content_path.is_file() or not metadata_path.is_file():
        raise ValueError("open-ended runtime task record is incomplete")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        content = content_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"open-ended runtime task record is unreadable: {exc}") from None
    if not isinstance(metadata, dict) or metadata.get("format") != TASK_RECORD_FORMAT:
        raise ValueError("open-ended runtime task metadata is invalid")
    if metadata.get("version") != TASK_RECORD_VERSION:
        raise ValueError("open-ended runtime task metadata version is unsupported")
    source_path = metadata.get("source_task_file")
    if source_path is not None and not isinstance(source_path, str):
        raise ValueError("open-ended runtime task metadata is invalid")
    task = _validated_task(content, source_path)
    if metadata.get("sha256") != task.sha256:
        raise ValueError("open-ended runtime task content does not match its recorded hash")
    return task


def resolve_open_ended_task(
    state_dir: Path,
    task_file: str | Path | None,
) -> OpenEndedTask:
    """Resolve task identity without writing runtime state.

    A new runtime requires a source file. Once persisted, the runtime-owned copy
    is sufficient; supplying the source again verifies that its exact bytes still
    identify the same task.
    """

    persisted = _load_persisted_task(state_dir)
    supplied: OpenEndedTask | None = None
    if task_file is not None:
        source = Path(task_file).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"--task-file must name a readable file: {source}")
        try:
            supplied = _validated_task(source.read_bytes(), str(source))
        except OSError as exc:
            raise ValueError(f"could not read --task-file {source}: {exc}") from None

    if persisted is None:
        if supplied is None:
            raise ValueError(
                "--task-file is required when initializing an open-ended runtime"
            )
        return supplied
    if supplied is not None and supplied.sha256 != persisted.sha256:
        raise ValueError(
            "--task-file does not match the task already recorded by this runtime"
        )
    return persisted


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _atomic_bytes(path, data)


class OpenEndedBenchmarkDriver:
    """Materialize a shared task without adding evaluation or model tools."""

    name = "open-ended"

    def __init__(self, config: OpenEndedConfig):
        self.config = config
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("open-ended benchmark driver is closed")

    def _persist_task(self) -> None:
        existing = _load_persisted_task(self.config.state_dir)
        if existing is not None:
            if existing.sha256 != self.config.task.sha256:
                raise ValueError("open-ended runtime task identity changed")
            return
        _atomic_bytes(
            self.config.state_dir / TASK_CONTENT_FILENAME,
            self.config.task.content,
        )
        _atomic_json(
            self.config.state_dir / TASK_METADATA_FILENAME,
            {
                "format": TASK_RECORD_FORMAT,
                "version": TASK_RECORD_VERSION,
                "sha256": self.config.task.sha256,
                "content_file": TASK_CONTENT_FILENAME,
                "source_task_file": self.config.task.source_path,
                "evaluation": "unconfigured",
            },
        )

    def prepare_batch(self, iteration_index: int, shared_workspace: Path) -> PreparedBatch:
        self._check_open()
        self._persist_task()
        shared_workspace.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(
            shared_workspace / "BENCHMARK.md",
            self.config.task.content,
        )
        return PreparedBatch(
            benchmark=self.name,
            iteration_index=iteration_index,
            item_count=0,
            metadata={
                "benchmark_readme_path": str(shared_workspace / "BENCHMARK.md"),
                "task_sha256": self.config.task.sha256,
                "task_state_dir": str(self.config.state_dir),
                "evaluation": "unconfigured",
                "has_problem_pool": False,
            },
        )

    def prepare_rollout(
        self,
        batch: PreparedBatch,
        *,
        backend: str,
        context: dict[str, Any],
    ) -> RolloutBenchmark:
        self._check_open()
        if batch.benchmark != self.name:
            raise ValueError("prepared batch belongs to a different profile")
        rollout_context = {
            **context,
            "open_ended_task_sha256": self.config.task.sha256,
            "evaluation": "unconfigured",
        }
        return RolloutBenchmark(
            context=rollout_context,
            model_metadata={
                "benchmark_readme": self.config.task.content.decode("utf-8"),
                "evaluation": "unconfigured",
                "tools": [],
            },
        )

    def collect_outcome(
        self,
        batch: PreparedBatch,
        *,
        instance_uuid: str,
        context: dict[str, Any],
    ) -> BenchmarkOutcome | None:
        self._check_open()
        return None

    def handle_tool(
        self,
        rollout: RolloutBenchmark,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        self._check_open()
        return None

    def finalize_batch(
        self,
        batch: PreparedBatch,
        outcomes: list[BenchmarkOutcome],
    ) -> dict[str, Any]:
        self._check_open()
        return {}

    def close(self) -> None:
        self._closed = True

"""Small lifecycle contract between benchmark logic and rollout orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class BenchmarkItemRef:
    """Public provenance for the benchmark item active in a rollout."""

    item_id: str
    source_id: str | None = None
    item_index: int | None = None
    iteration_index: int | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_id": self.source_id,
            "item_index": self.item_index,
            "iteration_index": self.iteration_index,
        }

    @classmethod
    def from_metadata(cls, value: Any) -> BenchmarkItemRef | None:
        if not isinstance(value, dict):
            return None
        item_id = value.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            return None
        source_id = value.get("source_id")
        if source_id is not None and (not isinstance(source_id, str) or not source_id):
            return None

        indices: list[int | None] = []
        for key in ("item_index", "iteration_index"):
            raw = value.get(key)
            if raw is None:
                indices.append(None)
                continue
            if isinstance(raw, bool):
                return None
            try:
                index = int(raw)
            except (TypeError, ValueError):
                return None
            if index < 0:
                return None
            indices.append(index)
        return cls(item_id, source_id, indices[0], indices[1])


def active_benchmark_item(context: dict[str, Any]) -> BenchmarkItemRef | None:
    """Return the latest generic item projection without benchmark knowledge."""

    events_path = context.get("benchmark_events_path")
    instance_uuid = context.get("instance_uuid")
    if isinstance(events_path, str) and isinstance(instance_uuid, str):
        try:
            lines = Path(events_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, dict) or event.get("instance_uuid") != instance_uuid:
                continue
            metadata = event.get("metadata")
            ref = BenchmarkItemRef.from_metadata(
                metadata.get("benchmark_item") if isinstance(metadata, dict) else None
            )
            if ref is not None:
                return ref
    return BenchmarkItemRef.from_metadata(context.get("active_benchmark_item"))


@dataclass(frozen=True)
class ScheduledBenchmarkBatch:
    iteration_index: int
    scheduler_id: str


@dataclass(frozen=True)
class PreparedBatch:
    benchmark: str
    iteration_index: int
    item_count: int
    metadata: dict[str, Any] = field(default_factory=dict)
    private: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class RolloutBenchmark:
    context: dict[str, Any]
    model_metadata: dict[str, Any]
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    sensitive_mcp_tools: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BenchmarkOutcome:
    instance_uuid: str
    attempted: bool
    solved: bool
    reward: float | None
    item_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    item_ref: BenchmarkItemRef | None = None
    run_record: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BenchmarkDriver(Protocol):
    name: str

    def prepare_batch(self, iteration_index: int, shared_workspace: Path) -> PreparedBatch: ...

    def prepare_rollout(
        self,
        batch: PreparedBatch,
        *,
        backend: str,
        context: dict[str, Any],
    ) -> RolloutBenchmark: ...

    def collect_outcome(
        self,
        batch: PreparedBatch,
        *,
        instance_uuid: str,
        context: dict[str, Any],
    ) -> BenchmarkOutcome | None:
        """Return an evaluated outcome, or None when no evaluator is configured."""
        ...

    def handle_tool(
        self,
        rollout: RolloutBenchmark,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def finalize_batch(
        self,
        batch: PreparedBatch,
        outcomes: list[BenchmarkOutcome],
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...

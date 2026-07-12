"""ARC-AGI benchmark lifecycle isolated from generic rollout orchestration."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from utils.arc_agi_client import ArcAgiClient
from utils.arc_agi_frames import MAX_SCALE
from utils.arc_agi_mcp import (
    CONTEXT_ENV,
    CONTEXT_SCHEMA,
    DRIVER_CONTEXT_VERSION,
    load_context,
)
from utils.arc_agi_rollout import (
    ArcAgiSessionSnapshot,
    close_arc_rollout,
    inspect_arc_rollout_session,
)
from utils.arc_agi_server import ArcAgiServerProcess, launch_arc_agi_server
from utils.arc_agi_tasks import environment_info_records, write_arc_task_pool
from utils.benchmark_driver import (
    BenchmarkItemRef,
    BenchmarkOutcome,
    PreparedBatch,
    RolloutBenchmark,
)
from utils.problem_pool_sampling import deterministic_problem_pool_sample


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARC_TOOL_NAMES = ("RESET", *(f"ACTION{index}" for index in range(1, 8)))


@dataclass(frozen=True)
class ArcAgiConfig:
    seed: int = 42
    problem_pool_size: int | None = None
    render_scale: int = 4
    server_readiness_timeout: float = 30.0
    mcp_startup_timeout_sec: int = 10
    mcp_tool_timeout_sec: int = 60
    audit_path: Path | None = None
    python_executable: str = sys.executable
    project_root: Path = PROJECT_ROOT

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.problem_pool_size is not None and (
            isinstance(self.problem_pool_size, bool)
            or not isinstance(self.problem_pool_size, int)
            or self.problem_pool_size <= 0
        ):
            raise ValueError("problem_pool_size must be a positive integer or None")
        if (
            isinstance(self.render_scale, bool)
            or not isinstance(self.render_scale, int)
            or not 1 <= self.render_scale <= MAX_SCALE
        ):
            raise ValueError(f"render_scale must be an integer from 1 through {MAX_SCALE}")
        if self.server_readiness_timeout <= 0:
            raise ValueError("server_readiness_timeout must be positive")
        if self.mcp_startup_timeout_sec <= 0 or self.mcp_tool_timeout_sec <= 0:
            raise ValueError("MCP timeouts must be positive")
        if not self.python_executable:
            raise ValueError("python_executable must be non-empty")


@dataclass(frozen=True)
class _ArcPoolItem:
    index: int
    uuid: str
    game_id: str
    record: dict[str, Any] = field(repr=False)


@dataclass
class _ArcRollout:
    instance_uuid: str
    context_path: Path = field(repr=False)
    state_path: Path = field(repr=False)
    state_root: Path = field(repr=False)
    rollout_root: Path = field(repr=False)


@dataclass
class _ArcBatch:
    iteration_index: int
    items: tuple[_ArcPoolItem, ...]
    server: ArcAgiServerProcess = field(repr=False)
    shared_workspace: Path = field(repr=False)
    by_uuid: dict[str, _ArcPoolItem] = field(repr=False)
    by_game_id: dict[str, _ArcPoolItem] = field(repr=False)
    rollouts: dict[str, _ArcRollout] = field(default_factory=dict, repr=False)
    closed: bool = False


class ArcAgiBenchmarkDriver:
    name = "arc-agi"

    def __init__(
        self,
        config: ArcAgiConfig,
        *,
        records_loader: Callable[[], Iterable[dict[str, Any]]] = environment_info_records,
        pool_writer: Callable[..., tuple[Path, Path]] = write_arc_task_pool,
        server_launcher: Callable[..., ArcAgiServerProcess] = launch_arc_agi_server,
        client_factory: Callable[[str], ArcAgiClient] = ArcAgiClient,
        snapshot_reader: Callable[[str | Path], ArcAgiSessionSnapshot] = inspect_arc_rollout_session,
        rollout_closer: Callable[[str | Path], dict[str, Any]] = close_arc_rollout,
    ) -> None:
        self.config = config
        self._records_loader = records_loader
        self._pool_writer = pool_writer
        self._server_launcher = server_launcher
        self._client_factory = client_factory
        self._snapshot_reader = snapshot_reader
        self._rollout_closer = rollout_closer
        self._batch: _ArcBatch | None = None
        self._closed = False
        self.cleanup_summary: dict[str, Any] | None = None
        self.finalization_summary: dict[str, Any] | None = None

    def prepare_batch(self, iteration_index: int, shared_workspace: Path) -> PreparedBatch:
        if self._closed:
            raise RuntimeError("ARC benchmark driver is closed")
        if self._batch is not None:
            raise RuntimeError("ARC benchmark driver already owns an active batch")
        if isinstance(iteration_index, bool) or not isinstance(iteration_index, int) or iteration_index < 0:
            raise ValueError("iteration_index must be a non-negative integer")

        records = self._validated_records(self._records_loader())
        sampled_records = deterministic_problem_pool_sample(
            records,
            problem_pool_size=self.config.problem_pool_size,
            seed=self.config.seed,
            iteration_index=iteration_index,
            record_id=lambda record: str(record["uuid"]),
        )
        if not sampled_records:
            raise RuntimeError("No ARC environments are available")
        items = tuple(
            _ArcPoolItem(index, str(record["uuid"]), str(record["game_id"]), record)
            for index, record in enumerate(sampled_records)
        )
        workspace = Path(shared_workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        final_json = workspace / "problem_pool.json"
        final_markdown = workspace / "problem_pool.md"
        server: ArcAgiServerProcess | None = None
        try:
            with tempfile.TemporaryDirectory(prefix=".arc-pool-", dir=workspace) as temporary:
                staging = Path(temporary)
                staged_json, staged_markdown = self._pool_writer(
                    json_path=staging / final_json.name,
                    markdown_path=staging / final_markdown.name,
                    records=sampled_records,
                    configured_problem_pool_size=self.config.problem_pool_size,
                    seed=self.config.seed,
                    iteration_index=iteration_index,
                )
                if not Path(staged_json).is_file() or not Path(staged_markdown).is_file():
                    raise RuntimeError("ARC pool writer did not produce both pool files")
                server = self._server_launcher(
                    readiness_timeout=self.config.server_readiness_timeout
                )
                os.replace(staged_json, final_json)
                os.replace(staged_markdown, final_markdown)
        except Exception:
            if server is not None:
                try:
                    server.terminate()
                except Exception:
                    pass
            raise

        batch_state = _ArcBatch(
            iteration_index=iteration_index,
            items=items,
            server=server,
            shared_workspace=workspace,
            by_uuid={item.uuid: item for item in items},
            by_game_id={item.game_id: item for item in items},
        )
        self._batch = batch_state
        return PreparedBatch(
            benchmark=self.name,
            iteration_index=iteration_index,
            item_count=len(items),
            metadata={
                "problem_pool_json_path": str(final_json),
                "problem_pool_markdown_path": str(final_markdown),
                "configured_problem_pool_size": self.config.problem_pool_size,
                "sampling_seed": self.config.seed,
            },
            private=batch_state,
        )

    def prepare_rollout(
        self,
        batch: PreparedBatch,
        *,
        backend: str,
        context: dict[str, Any],
    ) -> RolloutBenchmark:
        state = self._require_batch(batch)
        if backend != "codex":
            raise ValueError("ARC command MCP currently requires the Codex backend")
        instance_uuid = context.get("instance_uuid")
        if not isinstance(instance_uuid, str) or not instance_uuid:
            raise ValueError("rollout context must contain instance_uuid")
        if instance_uuid in state.rollouts:
            raise RuntimeError("ARC rollout is already prepared for this instance")

        continuation_path = _absolute_path(
            context.get("continuation_context_path"), "continuation_context_path"
        )
        workdir = _absolute_path(context.get("workdir"), "workdir")
        benchmark_events_path = _absolute_path(
            context.get("budget_ledger_events"), "budget_ledger_events"
        )
        control_root = continuation_path.parent
        raw_state_base = context.get("rollout_state_dir")
        state_base = (
            _absolute_path(raw_state_base, "rollout_state_dir")
            if raw_state_base is not None
            else control_root / "arc_state"
        )
        state_root = state_base / "arc_agi"
        rollout_root = workdir / "arc_agi_rollout"
        context_path = control_root / "arc_mcp_context.json"
        state_path = state_root / "arc_session.json"
        state_lock = state_path.with_name(f"{state_path.name}.lock")
        artifact_root = rollout_root / "arc_observations"
        if any(
            existing.context_path == context_path
            or existing.state_path == state_path
            or existing.rollout_root == rollout_root
            for existing in state.rollouts.values()
        ):
            raise RuntimeError("ARC rollout paths are not isolated")
        created: list[Path] = []
        try:
            for directory in (control_root, state_base, state_root, rollout_root):
                if not directory.exists():
                    created.append(directory)
                _private_directory(directory)
            _private_empty_file(state_lock)
            payload = {
                "schema": CONTEXT_SCHEMA,
                "version": DRIVER_CONTEXT_VERSION,
                "allowed_game_ids": [item.game_id for item in state.items],
                "base_url": state.server.base_url,
                "state_root": str(state_root),
                "state_path": str(state_path),
                "rollout_root": str(rollout_root),
                "artifact_root": str(artifact_root),
                "render_scale": self.config.render_scale,
                "instance_uuid": instance_uuid,
                "benchmark_events_path": str(benchmark_events_path),
                "benchmark_items": {
                    item.game_id: BenchmarkItemRef(
                        item_id=item.uuid,
                        source_id=item.game_id,
                        item_index=item.index,
                        iteration_index=state.iteration_index,
                    ).to_metadata()
                    for item in state.items
                },
            }
            _atomic_json(context_path, payload, mode=0o600)
            load_context(context_path)
            rollout = _ArcRollout(
                instance_uuid,
                context_path,
                state_path,
                state_root,
                rollout_root,
            )
            state.rollouts[instance_uuid] = rollout
        except Exception:
            context_path.unlink(missing_ok=True)
            state_lock.unlink(missing_ok=True)
            for directory in reversed(created):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise

        namespaced_tools = [f"mcp__arc_agi__{name}" for name in ARC_TOOL_NAMES]
        instructions = (
            "Choose an official game_id from the shared ARC pool and call "
            "mcp__arc_agi__RESET(game_id=...). Then issue only official ACTION commands "
            "whose integer IDs appear in the latest available_actions; ACTION6 requires "
            "integer x and y coordinates. Use the returned ordered frames and state."
        )
        benchmark_context = {
            **context,
            "arc_mcp_context_path": str(context_path),
            "arc_state_path": str(state_path),
        }
        return RolloutBenchmark(
            context=benchmark_context,
            model_metadata={
                "instructions": instructions,
                "tool_names": namespaced_tools,
                "fitness_pending": True,
            },
            mcp_servers={
                "arc_agi": {
                    "command": self.config.python_executable,
                    "args": ["-m", "utils.arc_agi_mcp"],
                    "cwd": str(self.config.project_root.resolve()),
                    "env": {CONTEXT_ENV: str(context_path)},
                    "required": True,
                    "enabled_tools": list(ARC_TOOL_NAMES),
                    "default_tools_approval_mode": "approve",
                    "startup_timeout_sec": self.config.mcp_startup_timeout_sec,
                    "tool_timeout_sec": self.config.mcp_tool_timeout_sec,
                }
            },
        )

    def collect_outcome(
        self,
        batch: PreparedBatch,
        *,
        instance_uuid: str,
        context: dict[str, Any],
    ) -> BenchmarkOutcome:
        state = self._require_batch(batch)
        rollout = self._require_rollout(state, instance_uuid, context)
        if not rollout.state_path.exists():
            return BenchmarkOutcome(
                instance_uuid=instance_uuid,
                attempted=False,
                solved=False,
                reward=0.0,
                error="ARC RESET was not called",
                metadata={"fitness_pending": True, "attempted": False},
                run_record={"fitness_pending": True, "attempted": False},
            )
        try:
            snapshot = self._snapshot_reader(rollout.state_path)
        except Exception:
            return BenchmarkOutcome(
                instance_uuid=instance_uuid,
                attempted=True,
                solved=False,
                reward=0.0,
                error="ARC rollout state is unavailable",
                metadata={"fitness_pending": True, "attempted": True},
                run_record={"fitness_pending": True, "attempted": True},
            )
        item = state.by_game_id.get(snapshot.game_id)
        if item is None:
            return BenchmarkOutcome(
                instance_uuid=instance_uuid,
                attempted=True,
                solved=False,
                reward=0.0,
                error="ARC rollout selected a game outside the prepared batch",
                metadata={"fitness_pending": True, "attempted": True},
                run_record={"fitness_pending": True, "attempted": True},
            )

        scorecard: dict[str, Any] | None = None
        scorecard_available = False
        if not snapshot.closed:
            try:
                scorecard = self._client_factory(snapshot.base_url).get_scorecard(
                    snapshot.card_id, snapshot.game_id
                )
                scorecard_available = True
            except Exception:
                scorecard = None
        metrics = _safe_scorecard_metrics(scorecard, snapshot.game_id)
        item_ref = BenchmarkItemRef(
            item_id=item.uuid,
            source_id=item.game_id,
            item_index=item.index,
            iteration_index=state.iteration_index,
        )
        safe = {
            "fitness_pending": True,
            "attempted": True,
            "game_id": item.game_id,
            "state": snapshot.state,
            "levels_completed": snapshot.levels_completed,
            "win_levels": snapshot.win_levels,
            "available_actions": list(snapshot.available_actions),
            "step_index": snapshot.step_index,
            "operation": snapshot.operation,
            "closed": snapshot.closed,
            "scorecard_available": scorecard_available,
            **metrics,
        }
        return BenchmarkOutcome(
            instance_uuid=instance_uuid,
            attempted=True,
            solved=False,
            reward=0.0,
            item_id=item.uuid,
            metadata=safe,
            item_ref=item_ref,
            run_record={**safe, "benchmark_item": item_ref.to_metadata()},
        )

    def handle_tool(
        self,
        rollout: RolloutBenchmark,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        return None

    def finalize_batch(
        self,
        batch: PreparedBatch,
        outcomes: list[BenchmarkOutcome],
    ) -> dict[str, Any]:
        state = self._require_batch(batch)
        selected = sorted({outcome.item_id for outcome in outcomes if outcome.item_id})
        state_counts = Counter(
            str(outcome.metadata.get("state"))
            for outcome in outcomes
            if outcome.metadata.get("state") is not None
        )
        summary = {
            "benchmark": self.name,
            "iteration_index": state.iteration_index,
            "item_count": len(state.items),
            "rollout_count": len(outcomes),
            "attempted_count": sum(outcome.attempted for outcome in outcomes),
            "selected_item_count": len(selected),
            "selected_item_ids": selected,
            "total_levels_completed": sum(
                _safe_int(outcome.metadata.get("levels_completed")) for outcome in outcomes
            ),
            "total_actions": sum(
                _safe_int(outcome.metadata.get("scorecard_total_actions")) for outcome in outcomes
            ),
            "state_counts": dict(sorted(state_counts.items())),
            "solved_count": 0,
            "reward_total": 0.0,
            "fitness_pending": True,
        }
        self.finalization_summary = summary
        if self.config.audit_path is not None:
            _atomic_json(Path(self.config.audit_path).resolve(), summary, mode=0o600)
        return summary

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        batch = self._batch
        errors: list[str] = []
        initialized = 0
        closed = 0
        if batch is not None:
            for rollout in batch.rollouts.values():
                if not rollout.state_path.exists():
                    continue
                initialized += 1
                try:
                    self._rollout_closer(rollout.state_path)
                    closed += 1
                except Exception:
                    errors.append("scorecard_close_failed")
            try:
                batch.server.terminate()
            except Exception:
                errors.append("server_terminate_failed")
            batch.closed = True
        self.cleanup_summary = {
            "initialized_rollout_count": initialized,
            "closed_rollout_count": closed,
            "cleanup_error_count": len(errors),
            "cleanup_errors": errors,
            "server_terminated": batch is not None and "server_terminate_failed" not in errors,
        }

    def _require_batch(self, batch: PreparedBatch) -> _ArcBatch:
        if self._closed:
            raise RuntimeError("ARC benchmark driver is closed")
        if (
            batch.benchmark != self.name
            or self._batch is None
            or batch.private is not self._batch
            or self._batch.closed
        ):
            raise ValueError("PreparedBatch does not belong to the active ARC batch")
        return self._batch

    @staticmethod
    def _validated_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        uuids: set[str] = set()
        games: set[str] = set()
        for raw in records:
            if not isinstance(raw, dict):
                raise ValueError("ARC environment records must be JSON objects")
            record = dict(raw)
            uuid = record.get("uuid")
            game_id = record.get("game_id")
            if not isinstance(uuid, str) or not uuid or not isinstance(game_id, str) or not game_id:
                raise ValueError("ARC environment records require uuid and game_id")
            if uuid in uuids:
                raise ValueError("ARC environment records contain a duplicate uuid")
            if game_id in games:
                raise ValueError("ARC environment records contain a duplicate game_id")
            uuids.add(uuid)
            games.add(game_id)
            normalized.append(record)
        return normalized

    @staticmethod
    def _require_rollout(
        batch: _ArcBatch,
        instance_uuid: str,
        context: dict[str, Any],
    ) -> _ArcRollout:
        rollout = batch.rollouts.get(instance_uuid)
        if rollout is None:
            raise ValueError("ARC rollout was not prepared for this instance")
        if context.get("arc_state_path") != str(rollout.state_path):
            raise ValueError("ARC rollout context does not match its prepared state")
        return rollout


def _safe_scorecard_metrics(value: Any, game_id: str) -> dict[str, int]:
    scorecard = value if isinstance(value, dict) else {}
    cards = scorecard.get("cards")
    card = cards.get(game_id) if isinstance(cards, dict) else None
    card = card if isinstance(card, dict) else {}
    actions = card.get("actions")
    resets = card.get("resets")
    return {
        "scorecard_played": _safe_int(scorecard.get("played")),
        "scorecard_won": _safe_int(scorecard.get("won")),
        "scorecard_total_actions": _safe_int(scorecard.get("total_actions")),
        "scorecard_levels_completed": _safe_int(scorecard.get("levels_completed")),
        "game_total_plays": _safe_int(card.get("total_plays")),
        "game_total_actions": _safe_int(card.get("total_actions")),
        "game_current_actions": _safe_int(actions[-1]) if isinstance(actions, list) and actions else 0,
        "game_total_resets": sum(_safe_int(item) for item in resets) if isinstance(resets, list) else 0,
    }


def _safe_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an absolute path")
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise ValueError(f"{label} must be an absolute normalized path")
    return path


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _private_empty_file(path: Path) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Any, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        temporary.unlink(missing_ok=True)

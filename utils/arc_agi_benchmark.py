"""ARC-AGI benchmark lifecycle isolated from generic rollout orchestration."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

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
ARC_BENCHMARK_README_PATH = PROJECT_ROOT / "seeds" / "benchmarks" / "arc_agi" / "README.md"
ARC_TOOL_NAMES = ("RESET", *(f"ACTION{index}" for index in range(1, 8)))
STATE_SCHEMA = "metalanguage.arc_benchmark_state"
STATE_VERSION = 1
_STATE_FIELDS = {"schema", "version", "config", "solved_items"}


@dataclass(frozen=True)
class ArcAgiConfig:
    state_path: Path
    seed: int = 42
    problem_pool_size: int | None = None
    solve_reward_token_credit_tokens: int = 0
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
            isinstance(self.solve_reward_token_credit_tokens, bool)
            or not isinstance(self.solve_reward_token_credit_tokens, int)
            or self.solve_reward_token_credit_tokens < 0
        ):
            raise ValueError("solve_reward_token_credit_tokens must be a non-negative integer")
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
        if not self.state_path.is_absolute():
            raise ValueError("state_path must be absolute")


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
    finalization_summary: dict[str, Any] | None = field(default=None, repr=False)
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
        self._cleanup_initialized = 0
        self._cleanup_closed = 0
        self._cleanup_errors: list[str] = []

    def prepare_batch(self, iteration_index: int, shared_workspace: Path) -> PreparedBatch:
        if self._closed:
            raise RuntimeError("ARC benchmark driver is closed")
        if self._batch is not None:
            raise RuntimeError("ARC benchmark driver already owns an active batch")
        if isinstance(iteration_index, bool) or not isinstance(iteration_index, int) or iteration_index < 0:
            raise ValueError("iteration_index must be a non-negative integer")

        records = self._validated_records(self._records_loader())
        with self._state_lock():
            solved_state = self._load_state_locked()
        solved_ids = {item["item_id"] for item in solved_state["solved_items"]}
        solved_games = {item["game_id"] for item in solved_state["solved_items"]}
        records_by_uuid = {str(record["uuid"]): record for record in records}
        records_by_game = {str(record["game_id"]): record for record in records}
        for solved in solved_state["solved_items"]:
            by_uuid = records_by_uuid.get(solved["item_id"])
            by_game = records_by_game.get(solved["game_id"])
            if (
                by_uuid is not None
                and by_uuid["game_id"] != solved["game_id"]
                or by_game is not None
                and by_game["uuid"] != solved["item_id"]
            ):
                raise RuntimeError("ARC benchmark state does not match the environment catalog")
        eligible_records = [
            record
            for record in records
            if record["uuid"] not in solved_ids
            and record["game_id"] not in solved_games
        ]
        sampled_records = deterministic_problem_pool_sample(
            eligible_records,
            problem_pool_size=self.config.problem_pool_size,
            seed=self.config.seed,
            iteration_index=iteration_index,
            record_id=lambda record: str(record["uuid"]),
        )
        if not sampled_records:
            raise RuntimeError("No unsolved ARC environments remain")
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
                "solve_reward_token_credit_tokens": (
                    self.config.solve_reward_token_credit_tokens
                ),
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
        benchmark_readme = ARC_BENCHMARK_README_PATH.read_text(encoding="utf-8")
        benchmark_context = {
            **context,
            "arc_mcp_context_path": str(context_path),
            "arc_state_path": str(state_path),
        }
        return RolloutBenchmark(
            context=benchmark_context,
            model_metadata={
                "benchmark_readme": benchmark_readme,
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
            mcp_budget_reconcile_tools=tuple(
                ("arc_agi", tool_name) for tool_name in ARC_TOOL_NAMES
            ),
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
        accounting = _safe_command_accounting(
            context.get("budget_ledger_events"),
            instance_uuid,
            item_ref,
        )
        credited_tokens = _safe_win_credit(
            context.get("budget_ledger_events"),
            instance_uuid,
            item_ref,
        )
        safe = {
            "fitness_pending": False,
            "completion_policy": "official_state_win",
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
            "reward": 1.0 if snapshot.state == "WIN" else 0.0,
            "reward_credit_claimed": credited_tokens > 0,
            "credited_tokens": credited_tokens,
            "configured_solve_reward_token_credit_tokens": (
                self.config.solve_reward_token_credit_tokens
            ),
            **metrics,
            **accounting,
        }
        safe["action_accounting_consistent"] = (
            scorecard_available
            and metrics["scorecard_total_actions"]
            == accounting["accounted_action_count"]
        )
        solved = snapshot.state == "WIN"
        return BenchmarkOutcome(
            instance_uuid=instance_uuid,
            attempted=True,
            solved=solved,
            reward=1.0 if solved else 0.0,
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
        if (
            isinstance(batch.private, _ArcBatch)
            and batch.private.finalization_summary is not None
        ):
            return batch.private.finalization_summary
        state = self._require_batch(batch)
        selected = sorted({outcome.item_id for outcome in outcomes if outcome.item_id})
        won_ids = {
            outcome.item_id
            for outcome in outcomes
            if outcome.solved
            and outcome.item_id in state.by_uuid
            and outcome.metadata.get("state") == "WIN"
        }
        with self._state_lock():
            persisted = self._load_state_locked()
            existing_ids = {
                item["item_id"] for item in persisted["solved_items"]
            }
            newly_solved = sorted(won_ids - existing_ids)
            already_solved = sorted(won_ids & existing_ids)
            known = {
                item["item_id"]: item for item in persisted["solved_items"]
            }
            for item_id in newly_solved:
                item = state.by_uuid[item_id]
                known[item_id] = {"item_id": item.uuid, "game_id": item.game_id}
            persisted["solved_items"] = [known[key] for key in sorted(known)]
            self._write_state_locked(persisted)
            total_solved = sorted(known)
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
            "total_accounted_actions": sum(
                _safe_int(outcome.metadata.get("accounted_action_count"))
                for outcome in outcomes
            ),
            "action_accounting_mismatch_count": sum(
                outcome.attempted
                and not bool(outcome.metadata.get("action_accounting_consistent"))
                for outcome in outcomes
            ),
            "state_counts": dict(sorted(state_counts.items())),
            "newly_solved_item_ids": newly_solved,
            "already_solved_item_ids": already_solved,
            "total_solved_item_ids": total_solved,
            "solved_count": len(won_ids),
            "reward_total": float(sum(outcome.reward for outcome in outcomes)),
            "credited_rollout_count": sum(
                bool(outcome.metadata.get("reward_credit_claimed"))
                for outcome in outcomes
            ),
            "solve_reward_credit_tokens_total": sum(
                _safe_int(outcome.metadata.get("credited_tokens"))
                for outcome in outcomes
            ),
            "fitness_pending": False,
            "completion_policy": "official_state_win",
        }
        self.finalization_summary = summary
        if self.config.audit_path is not None:
            _atomic_json(Path(self.config.audit_path).resolve(), summary, mode=0o600)
        state.finalization_summary = summary
        self._cleanup_batch(state)
        self._batch = None
        return summary

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        batch = self._batch
        if batch is not None:
            self._cleanup_batch(batch)
            self._batch = None
        self._update_cleanup_summary()

    def _cleanup_batch(self, batch: _ArcBatch) -> None:
        if batch.closed:
            return
        for rollout in batch.rollouts.values():
            if not rollout.state_path.exists():
                continue
            self._cleanup_initialized += 1
            try:
                self._rollout_closer(rollout.state_path)
                self._cleanup_closed += 1
            except Exception:
                self._cleanup_errors.append("scorecard_close_failed")
        try:
            batch.server.terminate()
        except Exception:
            self._cleanup_errors.append("server_terminate_failed")
        batch.closed = True
        self._update_cleanup_summary()

    def _update_cleanup_summary(self) -> None:
        self.cleanup_summary = {
            "initialized_rollout_count": self._cleanup_initialized,
            "closed_rollout_count": self._cleanup_closed,
            "cleanup_error_count": len(self._cleanup_errors),
            "cleanup_errors": list(self._cleanup_errors),
            "server_terminated": "server_terminate_failed" not in self._cleanup_errors,
        }

    @property
    def _state_config(self) -> dict[str, Any]:
        return {
            "benchmark": self.name,
            "task_source": "arc_agi_3",
            "seed": self.config.seed,
            "problem_pool_size": self.config.problem_pool_size,
        }

    def _load_state_locked(self) -> dict[str, Any]:
        path = self.config.state_path
        try:
            if path.stat().st_size > 1024 * 1024:
                raise RuntimeError("ARC benchmark state is too large")
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = {
                "schema": STATE_SCHEMA,
                "version": STATE_VERSION,
                "config": self._state_config,
                "solved_items": [],
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("ARC benchmark state is unreadable") from None
        if (
            not isinstance(value, dict)
            or set(value) != _STATE_FIELDS
            or value.get("schema") != STATE_SCHEMA
            or value.get("version") != STATE_VERSION
            or value.get("config") != self._state_config
        ):
            raise RuntimeError("ARC benchmark state is incompatible")
        solved = value.get("solved_items")
        if not isinstance(solved, list):
            raise RuntimeError("ARC benchmark state has invalid solved items")
        item_ids: set[str] = set()
        game_ids: set[str] = set()
        for item in solved:
            if (
                not isinstance(item, dict)
                or set(item) != {"item_id", "game_id"}
                or not isinstance(item.get("item_id"), str)
                or not item["item_id"]
                or not isinstance(item.get("game_id"), str)
                or not item["game_id"]
                or item["item_id"] in item_ids
                or item["game_id"] in game_ids
            ):
                raise RuntimeError("ARC benchmark state has invalid solved items")
            item_ids.add(item["item_id"])
            game_ids.add(item["game_id"])
        return value

    def _write_state_locked(self, value: dict[str, Any]) -> None:
        _atomic_json(self.config.state_path, value, mode=0o600)

    def _state_lock(self):
        return _locked_private_state(self.config.state_path)

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


def _safe_command_accounting(
    events_path: Any,
    instance_uuid: str,
    item_ref: BenchmarkItemRef,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if isinstance(events_path, str):
        try:
            lines = Path(events_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                isinstance(event, dict)
                and event.get("event_type") == "benchmark_command_completed"
                and event.get("instance_uuid") == instance_uuid
            ):
                metadata = event.get("metadata")
                if (
                    isinstance(metadata, dict)
                    and metadata.get("benchmark_item") == item_ref.to_metadata()
                ):
                    events.append(metadata)
    commands = Counter(
        metadata.get("command")
        for metadata in events
        if metadata.get("command") in ARC_TOOL_NAMES
    )
    return {
        "action_accounting_source": "benchmark_command_completed",
        "accounted_command_count": sum(commands.values()),
        "accounted_action_count": sum(
            count for command, count in commands.items() if command != "RESET"
        ),
        "accounted_reset_count": commands.get("RESET", 0),
        "accounted_actions": {
            command: commands.get(command, 0) for command in ARC_TOOL_NAMES
        },
    }


def _safe_win_credit(
    events_path: Any,
    instance_uuid: str,
    item_ref: BenchmarkItemRef,
) -> int:
    if not isinstance(events_path, str):
        return 0
    try:
        lines = Path(events_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    total = 0
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            continue
        if (
            not isinstance(event, dict)
            or event.get("event_type") != "solve_reward_credit"
            or event.get("instance_uuid") != instance_uuid
        ):
            continue
        metadata = event.get("metadata")
        if (
            isinstance(metadata, dict)
            and metadata.get("benchmark") == "arc-agi"
            and metadata.get("benchmark_item") == item_ref.to_metadata()
        ):
            total += _safe_int(event.get("amount_tokens"))
    return total


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


@contextmanager
def _locked_private_state(path: Path) -> Iterator[None]:
    _private_directory(path.parent)
    lock_path = path.with_name(f"{path.name}.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
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

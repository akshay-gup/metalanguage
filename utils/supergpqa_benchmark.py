"""SuperGPQA benchmark lifecycle, isolated from rollout orchestration."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from utils.benchmark_driver import BenchmarkItemRef, BenchmarkOutcome, PreparedBatch, RolloutBenchmark
from utils.hf_datasets import HFDatasetDataLoader
from utils.openrouter import submit_solution_tool
from utils.problem_pool_sampling import deterministic_problem_pool_sample
from utils.supergpqa_submit import latest_solution_scored_event, solution_scored_events, solve_reward_credit_total, submit_solution
from utils.task_store import compute_problem_uid, write_private_problem_record


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPERGPQA_BENCHMARK_README_PATH = (
    PROJECT_ROOT / "seeds" / "benchmarks" / "supergpqa" / "README.md"
)
CONTEXT_ENV = "METALANGUAGE_SUPERGPQA_CONTEXT"


def supergpqa_mcp_servers(context_path: Path) -> dict[str, Any]:
    return {
        "supergpqa": {
            "command": sys.executable,
            "args": ["-m", "utils.supergpqa_mcp"],
            "cwd": str(PROJECT_ROOT),
            "env": {CONTEXT_ENV: str(context_path.resolve())},
            "required": True,
            "enabled_tools": ["submit_solution"],
            "default_tools_approval_mode": "approve",
            "startup_timeout_sec": 10,
            "tool_timeout_sec": 30,
        }
    }


@dataclass(frozen=True)
class ProblemRecord:
    task_index: int
    task_id: str
    problem_uid: str
    task_markdown: str
    private_problem_path: Path


@dataclass(frozen=True)
class SuperGpqaConfig:
    dataset_name: str
    split: str
    config_name: str | None
    seed: int
    question_key: str | None
    answer_key: str | None
    id_key: str | None
    difficulty_filter: tuple[str, ...] | None
    start_task_index: int
    problem_pool_size: int | None
    solve_reward_token_credit_tokens: int
    queue_path: Path
    task_store_dir: Path
    dataset_cache_dir: Path
    historical_run_records: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    backend: str = "codex"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _payload(record: ProblemRecord) -> dict[str, Any]:
    return {
        "task_index": record.task_index,
        "task_id": record.task_id,
        "problem_uid": record.problem_uid,
        "task_markdown": record.task_markdown,
        "private_problem_path": str(record.private_problem_path),
    }


def _item_ref_from_solution_metadata(metadata: Any) -> BenchmarkItemRef | None:
    if not isinstance(metadata, dict):
        return None
    current = BenchmarkItemRef.from_metadata(metadata.get("benchmark_item"))
    if current is not None:
        return current
    item_id = metadata.get("problem_uid")
    source_id = metadata.get("task_id")
    item_index = metadata.get("problem_task_index")
    if not isinstance(item_id, str) or not item_id:
        return None
    try:
        normalized_index = int(item_index)
    except (TypeError, ValueError):
        normalized_index = None
    return BenchmarkItemRef(
        item_id=item_id,
        source_id=source_id if isinstance(source_id, str) and source_id else None,
        item_index=normalized_index,
        iteration_index=None,
    )


class SuperGpqaBenchmarkDriver:
    name = "supergpqa"

    def __init__(self, config: SuperGpqaConfig, *, rows: Iterable[dict[str, Any]] | None = None):
        self.config = config
        self._rows = list(rows) if rows is not None else None
        self._closed = False

    @property
    def queue_config(self) -> dict[str, Any]:
        c = self.config
        return {
            "dataset_name": c.dataset_name,
            "split": c.split,
            "config_name": c.config_name,
            "seed": c.seed,
            "question_key": c.question_key,
            "answer_key": c.answer_key,
            "id_key": c.id_key,
            "difficulty_filter": list(c.difficulty_filter) if c.difficulty_filter else None,
        }

    def _iter_rows(self) -> Iterable[tuple[int, dict[str, Any]]]:
        if self._rows is not None:
            yield from enumerate(self._rows)
            return
        loader = HFDatasetDataLoader(
            dataset_name=self.config.dataset_name,
            split=self.config.split,
            config_name=self.config.config_name,
            batch_size=1,
            shuffle=True,
            seed=self.config.seed,
            cache_dir=str(self.config.dataset_cache_dir),
        )
        for index, batch in enumerate(loader):
            yield index, batch[0]

    @staticmethod
    def _first(row: dict[str, Any], keys: list[str | None]) -> Any:
        return next((row[key] for key in keys if key and row.get(key) is not None), None)

    def _materialize_record(self, index: int, row: dict[str, Any]) -> ProblemRecord | None:
        difficulty = self.config.difficulty_filter
        if difficulty and str(row.get("difficulty", "")).strip().lower() not in difficulty:
            return None
        question = self._first(row, [self.config.question_key, "question", "problem", "prompt", "input"])
        answer = self._first(row, [self.config.answer_key, "answer", "solution", "ground_truth", "target"])
        task_id = self._first(row, [self.config.id_key, "id", "task_id", "problem_id", "uuid", "index"])
        if question is None or answer is None:
            raise ValueError("Could not infer question/answer fields from SuperGPQA row")
        if task_id is None:
            digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:12]
            task_id = f"row_{digest}"
        task_id = str(task_id)
        uid = compute_problem_uid(
            dataset_name=self.config.dataset_name,
            split=self.config.split,
            config_name=self.config.config_name,
            task_id=task_id,
            question=str(question),
        )
        private = write_private_problem_record(
            task_store_dir=self.config.task_store_dir,
            problem_uid=uid,
            row=row,
        )
        lines = ["# Task", "", "## Question", "", str(question).strip()]
        options = self._first(row, ["options", "choices", "answer_choices", "candidates"])
        if isinstance(options, list) and options:
            lines.extend(["", "## Options", ""])
            lines.extend(
                f"{chr(65 + index) if index < 26 else index}. {option}"
                for index, option in enumerate(options)
            )
        elif isinstance(options, dict) and options:
            lines.extend(["", "## Options", ""])
            lines.extend(f"- {key}: {option}" for key, option in options.items())
        lines.append("")
        markdown = "\n".join(lines)
        return ProblemRecord(index, task_id, uid, markdown, private)

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.config.queue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = {}
        if not isinstance(value, dict) or value.get("config") != self.queue_config:
            value = {}
        solved = value.get("solved_problem_uids", [])
        try:
            next_task_index = int(value.get("next_task_index", self.config.start_task_index))
        except (TypeError, ValueError):
            next_task_index = self.config.start_task_index
        historical_solved: set[str] = set()
        for record in self.config.historical_run_records:
            if record.get("solved") and record.get("problem_uid"):
                historical_solved.add(str(record["problem_uid"]))
            values = record.get("solved_problem_uids")
            if isinstance(values, list):
                historical_solved.update(str(value) for value in values if value)
        return {
            "config": self.queue_config,
            "next_task_index": max(next_task_index, self.config.start_task_index),
            "problems": [],
            "assigned_problems": value.get("assigned_problems", {}) if isinstance(value.get("assigned_problems"), dict) else {},
            "solved_problem_uids": sorted(
                {str(item) for item in solved if item} | historical_solved
            ),
        }

    def prepare_batch(self, iteration_index: int, shared_workspace: Path) -> PreparedBatch:
        if self._closed:
            raise RuntimeError("benchmark driver is closed")
        path = self.config.queue_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(path.suffix + ".lock").open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._load_state()
            solved = set(state["solved_problem_uids"])
            records = [record for index, row in self._iter_rows() if index >= self.config.start_task_index if (record := self._materialize_record(index, row)) is not None and record.problem_uid not in solved]
            state["next_task_index"] = max([self.config.start_task_index, *(record.task_index + 1 for record in records)])
            state["assigned_problems"] = {}
            _atomic_json(path, state)
        sampled = deterministic_problem_pool_sample(
            records,
            problem_pool_size=self.config.problem_pool_size,
            seed=self.config.seed,
            iteration_index=iteration_index,
            record_id=lambda record: record.problem_uid,
        )
        if not sampled:
            raise RuntimeError("No unsolved SuperGPQA problems remain")
        json_path = shared_workspace / "problem_pool.json"
        markdown_path = shared_workspace / "problem_pool.md"
        self._write_pool(
            sampled,
            json_path,
            markdown_path,
            backend=self.config.backend,
            iteration_index=iteration_index,
        )
        return PreparedBatch(
            self.name,
            iteration_index,
            len(sampled),
            {"problem_pool_json_path": str(json_path), "problem_pool_markdown_path": str(markdown_path)},
            tuple(sampled),
        )

    def _write_pool(
        self,
        records: list[ProblemRecord] | tuple[ProblemRecord, ...],
        json_path: Path,
        markdown_path: Path,
        *,
        backend: str,
        iteration_index: int,
    ) -> None:
        tool = "mcp__supergpqa__submit_solution" if backend == "codex" else "submit_solution"
        instruction = f"Choose a problem by uuid and submit with {tool}(uuid=..., answer=...)."
        payload = {
            "metadata": {"pool_scope": "sampled_working_set" if self.config.problem_pool_size is not None else "full_unsolved_pool", "configured_problem_pool_size": self.config.problem_pool_size, "iteration_index": iteration_index, "problem_pool_count": len(records), "sampling_seed": self.config.seed},
            "instructions": instruction,
            "problems": [{"uuid": record.problem_uid, "problem_markdown": record.task_markdown} for record in records],
        }
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text("# Problem Pool\n\n" + instruction + "\n\n" + "\n\n".join(f"## `{record.problem_uid}`\n\n{record.task_markdown.strip()}" for record in records) + "\n", encoding="utf-8")

    def prepare_rollout(self, batch: PreparedBatch, *, backend: str, context: dict[str, Any]) -> RolloutBenchmark:
        records = list(batch.private)
        json_path = Path(batch.metadata["problem_pool_json_path"])
        markdown_path = Path(batch.metadata["problem_pool_markdown_path"])
        if backend != self.config.backend:
            raise ValueError("rollout backend does not match prepared benchmark batch")
        benchmark_context = {
            **context,
            "problem_queue_path": str(self.config.queue_path),
            "problem_pool_config": self.queue_config,
            "problem_pool_start_task_index": self.config.start_task_index,
            "problem_pool_records": [_payload(record) for record in records],
            "problem_pool_json_path": str(json_path),
            "problem_pool_markdown_path": str(markdown_path),
            "configured_problem_pool_size": self.config.problem_pool_size,
            "problem_pool_count": len(records),
            "task_store_dir": str(self.config.task_store_dir),
            "dataset_cache_dir": str(self.config.dataset_cache_dir),
            "solve_reward_token_credit_tokens": self.config.solve_reward_token_credit_tokens,
        }
        latest = latest_solution_scored_event(
            Path(str(context["budget_ledger_events"])),
            str(context.get("instance_uuid") or ""),
        )
        historical_ref = _item_ref_from_solution_metadata(
            latest.get("metadata") if isinstance(latest, dict) else None
        )
        if historical_ref is not None:
            benchmark_context["active_benchmark_item"] = historical_ref.to_metadata()
        submit_tool = (
            "mcp__supergpqa__submit_solution"
            if backend == "codex"
            else "submit_solution"
        )
        benchmark_readme = SUPERGPQA_BENCHMARK_README_PATH.read_text(
            encoding="utf-8"
        ).format(
            submit_tool=submit_tool,
        )
        if backend != "codex":
            return RolloutBenchmark(
                benchmark_context,
                {
                    "benchmark_readme": benchmark_readme,
                    "submit_tool": submit_tool,
                    "tools": [submit_solution_tool],
                },
            )
        context_path = Path(str(context["continuation_context_path"]))
        mcp = supergpqa_mcp_servers(context_path)
        return RolloutBenchmark(
            benchmark_context,
            {"benchmark_readme": benchmark_readme, "submit_tool": submit_tool},
            mcp,
            (("supergpqa", "submit_solution"),),
            (("supergpqa", "submit_solution"),),
        )

    def handle_tool(self, rollout: RolloutBenchmark, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        if tool_name != rollout.model_metadata.get("submit_tool") or tool_name != "submit_solution":
            return None
        return submit_solution(context=rollout.context, args=arguments)

    def collect_outcome(self, batch: PreparedBatch, *, instance_uuid: str, context: dict[str, Any]) -> BenchmarkOutcome:
        events = solution_scored_events(Path(str(context["budget_ledger_events"])), instance_uuid)
        if not events:
            return BenchmarkOutcome(
                instance_uuid,
                False,
                False,
                0.0,
                error="submit_solution was not called",
                run_record={
                    "task_id": None,
                    "problem_uid": None,
                    "problem_task_index": None,
                    "active_assignment_problem_uid": None,
                    "submitted_uuid": None,
                    "reported_problem_uid": None,
                    "reported_task_id": None,
                    "solution_count": 0,
                    "solved_problem_count": 0,
                    "solved_problem_uids": [],
                    "solved_task_ids": [],
                    "solve_reward_credit_tokens": 0,
                    "solution_feedback": None,
                    "private_problem_path": None,
                },
            )
        rows = [event.get("metadata") if isinstance(event.get("metadata"), dict) else {} for event in events]
        latest = rows[-1]
        solved_ids = list(dict.fromkeys(str(row["problem_uid"]) for row in rows if row.get("solved") and row.get("problem_uid")))
        solved_tasks = list(dict.fromkeys(str(row["task_id"]) for row in rows if row.get("solved") and row.get("task_id")))
        reward = sum(float(row.get("reward") or 0.0) for row in rows)
        credit = solve_reward_credit_total(Path(str(context["budget_ledger_events"])), instance_uuid)
        feedback = {
            "correct": bool(latest.get("solved")),
            "solved": bool(solved_ids),
            "solution_count": len(events),
            "solved_problem_count": len(solved_ids),
            "solved_problem_uids": solved_ids,
            "solved_task_ids": solved_tasks,
            "reward": reward,
            "latest_reward": float(latest.get("reward") or 0.0),
            "credited_tokens": int(latest.get("solve_reward_credit_tokens") or 0),
            "total_credited_tokens": credit,
            "submitted_uuid": latest.get("submitted_uuid"),
        }
        item_ref = _item_ref_from_solution_metadata(latest)
        return BenchmarkOutcome(
            instance_uuid,
            True,
            bool(solved_ids),
            reward,
            str(latest.get("problem_uid") or "") or None,
            metadata={
                "task_id": latest.get("task_id"),
                "problem_task_index": latest.get("problem_task_index"),
                "active_assignment_problem_uid": None,
                "solution_count": len(events),
                "solved_item_ids": solved_ids,
                "solved_task_ids": solved_tasks,
                "credit_tokens": credit,
                "feedback": feedback,
            },
            item_ref=item_ref,
            run_record={
                "task_id": latest.get("task_id"),
                "problem_uid": latest.get("problem_uid"),
                "problem_task_index": latest.get("problem_task_index"),
                "solution_count": len(events),
                "solved_problem_count": len(solved_ids),
                "solved_problem_uids": solved_ids,
                "solved_task_ids": solved_tasks,
                "solve_reward_credit_tokens": credit,
                "solution_feedback": feedback,
                "submitted_uuid": latest.get("submitted_uuid"),
                "reported_problem_uid": None,
                "reported_task_id": None,
                "private_problem_path": None,
            },
        )

    def finalize_batch(self, batch: PreparedBatch, outcomes: list[BenchmarkOutcome]) -> dict[str, Any]:
        solved = {outcome.item_id for outcome in outcomes if outcome.solved and outcome.item_id}
        path = self.config.queue_path
        with path.with_suffix(path.suffix + ".lock").open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._load_state()
            state["solved_problem_uids"] = sorted(set(state["solved_problem_uids"]) | solved)
            _atomic_json(path, state)
        return {"solved_item_ids": sorted(solved), "solved_count": len(solved)}

    def close(self) -> None:
        self._closed = True

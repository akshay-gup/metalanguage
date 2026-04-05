#!/usr/bin/env python3
"""Minimal RLVR episode loop.

Flow:
1) Sample one task from a Hugging Face RLVR-style dataset.
2) Create an ephemeral episode temp directory and write task metadata.
3) Run a tool-using worker (LLM + bash function tool) in that directory.
4) Evaluate `solution.md` against ground truth with reward util.
5) Append run metadata to a growing JSONL log.
6) Print a one-line summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.hf_datasets import HFDatasetDataLoader
from utils.openrouter import bash_tool, call_openrouter_with_tools, get_tool_calls
from utils.reward import compute_score_bigmath


@dataclass
class Task:
    task_id: str
    question: str
    answer: str
    raw: dict[str, Any]


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def sample_task(
    *,
    dataset_name: str,
    split: str,
    config_name: str | None,
    seed: int,
    question_key: str | None,
    answer_key: str | None,
    id_key: str | None,
) -> Task:
    loader = HFDatasetDataLoader(
        dataset_name=dataset_name,
        split=split,
        config_name=config_name,
        batch_size=1,
        shuffle=True,
        seed=seed,
    )

    batch = next(iter(loader))
    row = batch[0]

    q = _first_present(row, [question_key] if question_key else [])
    if q is None:
        q = _first_present(row, ["question", "problem", "prompt", "input"])

    a = _first_present(row, [answer_key] if answer_key else [])
    if a is None:
        a = _first_present(row, ["answer", "solution", "ground_truth", "target"])

    tid = _first_present(row, [id_key] if id_key else [])
    if tid is None:
        tid = _first_present(row, ["id", "task_id", "problem_id", "index"])

    if q is None or a is None:
        keys = ", ".join(sorted(row.keys()))
        raise ValueError(
            "Could not infer question/answer fields from dataset row. "
            f"Available keys: {keys}. Pass --question-key/--answer-key explicitly."
        )

    if tid is None:
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:12]
        tid = f"row_{digest}"

    return Task(task_id=str(tid), question=str(q), answer=str(a), raw=row)


def _extract_text_from_response(response_json: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response_json.get("output", []):
        if item.get("type") != "message":
            continue
        for chunk in item.get("content", []):
            if not isinstance(chunk, dict):
                continue
            if chunk.get("type") in {"output_text", "text"} and chunk.get("text"):
                parts.append(str(chunk["text"]))
    return "\n".join(parts).strip()


def _run_bash_tool(command: str, working_directory: str) -> dict[str, Any]:
    proc = subprocess.run(
        command,
        shell=True,
        cwd=working_directory,
        text=True,
        capture_output=True,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "working_directory": working_directory,
    }


def run_worker(
    *,
    api_key: str,
    model: str,
    question: str,
    task_id: str,
    workdir: Path,
    max_turns: int,
) -> str:
    """Run a multi-turn tool-calling worker loop and return final assistant text.

    Stop only when either:
      1) the model returns no tool call and `solution.md` already exists, or
      2) max_turns is reached.
    """
    user_prompt = (
        "You are solving one RL task. Use bash when useful. "
        "All files must be created in the provided working directory. "
        "Write your final answer to solution.md in this exact format: \\boxed{...}.\n\n"
        f"Task ID: {task_id}\n"
        f"Working directory: {workdir}\n"
        f"Question:\n{question}\n"
    )

    conversation: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": user_prompt}],
        }
    ]

    final_text = ""
    for _ in range(max_turns):
        response = call_openrouter_with_tools(
            api_key=api_key,
            model=model,
            input_items=conversation,
            tools=[bash_tool],
            tool_choice="auto",
            max_output_tokens=4000,
            timeout=120,
        )

        if not isinstance(response, dict):
            raise RuntimeError("Unexpected non-JSON response in non-stream mode.")

        tool_calls = get_tool_calls(response)
        if not tool_calls:
            final_text = _extract_text_from_response(response)
            if (workdir / "solution.md").exists():
                break

            conversation.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Continue. You must write your final answer to "
                                "solution.md in the working directory before finishing."
                            ),
                        }
                    ],
                }
            )
            continue

        for call in tool_calls:
            args: dict[str, Any]
            raw_args = call.get("arguments", "{}")
            if isinstance(raw_args, str):
                args = json.loads(raw_args)
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            command = str(args.get("command", "")).strip()
            if not command:
                tool_result = {"error": "missing command"}
            else:
                wd = str(args.get("working_directory") or workdir)
                wd = wd if Path(wd).resolve().is_relative_to(workdir.resolve()) else str(workdir)
                tool_result = _run_bash_tool(command=command, working_directory=wd)

            conversation.append(call)
            conversation.append(
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": json.dumps(tool_result),
                }
            )

    return final_text


def persist_episode_outputs(temp_dir: Path, dest_root: Path, task_id: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_root / f"{ts}_{task_id}"
    shutil.copytree(temp_dir, dest, dirs_exist_ok=True)
    return dest


def append_run_log(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one RLVR episode.")
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--split", default="train")
    parser.add_argument("--config-name", default=None)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument("--question-key", default=None)
    parser.add_argument("--answer-key", default=None)
    parser.add_argument("--id-key", default=None)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--runs-log", default="logs/runs.jsonl")
    parser.add_argument("--outputs-dir", default="logs/episodes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required.")

    task = sample_task(
        dataset_name=args.dataset_name,
        split=args.split,
        config_name=args.config_name,
        seed=args.seed,
        question_key=args.question_key,
        answer_key=args.answer_key,
        id_key=args.id_key,
    )

    with tempfile.TemporaryDirectory(prefix="episode_") as tmp:
        temp_dir = Path(tmp)
        task_file = temp_dir / "task.json"
        task_file.write_text(
            json.dumps(
                {
                    "task_id": task.task_id,
                    "question": task.question,
                    "ground_truth": task.answer,
                    "dataset_row": task.raw,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        worker_text = run_worker(
            api_key=api_key,
            model=args.model,
            question=task.question,
            task_id=task.task_id,
            workdir=temp_dir,
            max_turns=args.max_turns,
        )

        solution_path = temp_dir / "solution.md"
        if not solution_path.exists():
            fallback = worker_text if worker_text else "\\boxed{}"
            solution_path.write_text(fallback + "\n", encoding="utf-8")

        solution_text = solution_path.read_text(encoding="utf-8")
        reward = compute_score_bigmath(solution_text, task.answer, {"problem_id": task.task_id})
        solved = bool(reward >= 1.0)

        output_dir = persist_episode_outputs(temp_dir, Path(args.outputs_dir), task.task_id)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "generation": args.generation,
        "seed": args.seed,
        "task_id": task.task_id,
        "solved": solved,
        "reward": reward,
        "output_path": str(output_dir),
        "dataset_name": args.dataset_name,
        "split": args.split,
        "model": args.model,
    }
    append_run_log(Path(args.runs_log), record)

    print(
        f"gen={args.generation} seed={args.seed} task_id={task.task_id} "
        f"solved={solved} output={output_dir}"
    )


if __name__ == "__main__":
    main()

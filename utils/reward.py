# train_grpo_limr_zero3.py
# pip install "evalchemy @ git+https://github.com/mlfoundations/evalchemy.git"
import os, re, json, argparse, sys, subprocess, glob, time, datetime
from typing import Optional, List, Any, Dict, Set
from math_verify import LatexExtractionConfig, parse, verify, math_metric, ExprExtractionConfig
from latex2sympy2_extended import NormalizationConfig
from bench_eval import compute_score_aime, compute_score_gpqa
from filelock import FileLock
from transformers import PreTrainedTokenizer
import aiohttp
from openai.types.chat import ChatCompletion
import math
import hashlib
import tempfile
from pathlib import Path
from functools import lru_cache

import requests
import pandas as pd
from filelock import FileLock

PISTON_ENDPOINT = os.environ.get("PISTON_ENDPOINT", "http://localhost:2000")
CF_GENERATED_TESTS_DIR = os.environ.get("CF_GENERATED_TESTS", "")
PISTON_TIMEOUT = int(os.environ.get("PISTON_TIMEOUT", "30"))  # seconds per request

# How many generated tests to use per problem (keep low for speed during training)
MAX_GENERATED_TESTS = int(os.environ.get("CF_MAX_GENERATED_TESTS", "3"))

# Language → Piston language identifier
LANG_MAP = {
    "python": ("py", "cf_python3"),
    "cpp":    ("cpp", "cf_c++17"),
    "c++":    ("cpp", "cf_c++17"),
}

_generated_tests_cache: dict[str, list[dict]] = {}

def _store_solution_output(solution_str, ground_truth, extra_info, num_problems):
    """
    Store the model's solution_str as JSON, indexed by a unique identifier.
    Overwrites if the same multi-problem prompt appears again.
    """
    # Create output directory if it doesn't exist
    output_dir = "multi_problem_outputs"
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique identifier for this multi-problem set
    # Use extra_info if it has a unique ID, otherwise hash the ground_truth
    if extra_info and "problem_id" in extra_info:
        unique_id = extra_info["problem_id"]
    elif extra_info and "index" in extra_info:
        unique_id = f"idx_{extra_info['index']}"
    else:
        # Hash the ground_truth to create a unique identifier
        gt_str = json.dumps(ground_truth, sort_keys=True) if not isinstance(ground_truth, str) else ground_truth
        unique_id = hashlib.md5(gt_str.encode()).hexdigest()[:12]
    
    # Clean the ID for use as filename
    safe_id = re.sub(r'[^\w\-]', '_', str(unique_id))
    filepath = os.path.join(output_dir, f"solution_{safe_id}.json")
    
    # Prepare data to store
    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "unique_id": unique_id,
        "num_problems": num_problems,
        "solution_str": solution_str,
        "ground_truth": ground_truth,
        "extra_info": extra_info
    }
    
    # Write to file (overwriting if exists)
    # Use FileLock to prevent race conditions in multi-process training
    lock_path = filepath + ".lock"
    try:
        with FileLock(lock_path, timeout=10):
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Failed to store solution output to {filepath}: {e}")

def _load_generated_tests_for_contest(contest_id: str) -> pd.DataFrame | None:
    """Load a single contest's generated test parquet file."""
    if not CF_GENERATED_TESTS_DIR:
        return None

    parquet_path = os.path.join(
        CF_GENERATED_TESTS_DIR, "generated_tests", f"test_cases_{contest_id}.parquet"
    )
    if not os.path.exists(parquet_path):
        return None

    try:
        return pd.read_parquet(parquet_path)
    except Exception as e:
        print(f"[cf_reward] Warning: failed to load {parquet_path}: {e}")
        return None

def get_generated_tests(problem_id: str, max_tests: int = MAX_GENERATED_TESTS) -> list[dict]:
    """
    Retrieve generated test cases for a problem.

    problem_id format is typically like "1234_A" or "1234A".
    Contest ID is the numeric prefix.
    """
    if problem_id in _generated_tests_cache:
        return _generated_tests_cache[problem_id][:max_tests]

    # Extract contest ID from problem_id (e.g. "1234_A" → "1234", "1234A" → "1234")
    match = re.match(r"(\d+)", str(problem_id))
    if not match:
        return []

    contest_id = match.group(1)
    df = _load_generated_tests_for_contest(contest_id)

    if df is None or df.empty:
        _generated_tests_cache[problem_id] = []
        return []

    # Cache all problems from this contest at once
    for pid, group in df.groupby("problem_id"):
        # Sort by test_case_i (lower = harder, based on dataset card's ordering)
        group = group.sort_values("test_case_i")
        tests = [{"input": row["input"], "output": row["output"]} for _, row in group.iterrows()]
        _generated_tests_cache[str(pid)] = tests

    return _generated_tests_cache.get(problem_id, [])[:max_tests]

def _execute_solution(
    source_code: str,
    test_input: str,
    test_output: str,
    language: str = "python",
    time_limit: float | None = None,
    memory_limit: float | None = None,
    input_mode: str = "stdio",
    generated_checker: str | None = None,
) -> bool:
    """
    Execute a single solution against a single test case via Piston.
    Returns True if the solution is correct, False otherwise.
    """
    extension, piston_language = LANG_MAP.get(language, LANG_MAP["python"])

    files = [
        {"name": f"main.{extension}", "content": source_code},
        {"name": "input.txt", "content": test_input},
        {"name": "correct_output.txt", "content": test_output},
    ]

    if generated_checker:
        files.append({"name": "checker.py", "content": generated_checker})

    config_parts = []
    if time_limit is not None:
        config_parts.append(f"TIME_LIMIT={time_limit}")
    if memory_limit is not None:
        config_parts.append(f"MEMORY_LIMIT={memory_limit}")
    if input_mode:
        config_parts.append(f"INPUT_MODE={input_mode}")

    if config_parts:
        files.append({"name": "grader_config", "content": "\n".join(config_parts)})

    payload = {
        "language": piston_language,
        "version": "*",
        "files": files,
    }

    try:
        resp = requests.post(
            f"{PISTON_ENDPOINT}/execute",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=PISTON_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.Timeout:
        return False
    except Exception as e:
        print(f"[cf_reward] Piston request failed: {e}")
        return False

    # Check result: compile success + run success + stdout starts with "1"
    if not result:
        return False
    compile_info = result.get("compile", {})
    run_info = result.get("run", {})

    if compile_info.get("code", -1) != 0:
        return False
    if run_info.get("code", -1) != 0:
        return False

    stdout = (run_info.get("stdout") or "").strip()
    return stdout.split()[0] == "1" if stdout else False

def _execute_solution_batch(
    source_code: str,
    tests: list[dict],
    language: str = "python",
    time_limit: float | None = None,
    memory_limit: float | None = None,
    input_mode: str = "stdio",
    generated_checker: str | None = None,
    fail_fast: bool = True,
) -> tuple[int, int]:
    """
    Run a solution against multiple test cases.
    Returns (num_passed, num_total).

    If fail_fast=True, stops on first failure (faster during training).
    """
    passed = 0
    total = len(tests)

    for test in tests:
        is_correct = _execute_solution(
            source_code=source_code,
            test_input=test["input"],
            test_output=test["output"],
            language=language,
            time_limit=time_limit,
            memory_limit=memory_limit,
            input_mode=input_mode,
            generated_checker=generated_checker,
        )
        if is_correct:
            passed += 1
        elif fail_fast:
            return passed, total

    return passed, total


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def ground_truth_from_private_row(private_problem_path: Path) -> tuple[str | None, str | None]:
    try:
        row = json.loads(private_problem_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None

    if not isinstance(row, dict):
        return None, None

    private_task_id = _first_present(row, ["id", "task_id", "problem_id", "index"])
    private_answer = _first_present(row, ["answer", "solution", "ground_truth", "target"])
    return (
        str(private_task_id) if private_task_id is not None else None,
        str(private_answer) if private_answer is not None else None,
    )


def compute_rollout_reward(
    *,
    submitted_answer: str,
    expected_task_id: str,
    expected_problem_uid: str,
    reported_task_id: str | None,
    reported_problem_uid: str | None,
    private_problem_path: Path,
) -> float:
    private_task_id, private_answer = ground_truth_from_private_row(private_problem_path)
    if private_answer is None:
        return 0.0

    if reported_problem_uid is not None and reported_problem_uid != expected_problem_uid:
        return 0.0
    if reported_task_id is not None and reported_task_id != expected_task_id:
        return 0.0
    if private_task_id is not None and private_task_id != expected_task_id:
        return 0.0

    return compute_score_bigmath(submitted_answer, private_answer, {"problem_id": expected_task_id})

def _extract_code_from_section(section_text: str, language: str = "python") -> str | None:
    """
    Extract the last code block from a section of model output.
    Handles ```python ... ```, ```cpp ... ```, or bare ``` ... ```.
    Returns None if no code block found or SKIP detected.
    """
    if not section_text:
        return None

    # Check for SKIP
    if re.search(r'\bSKIP\b', section_text, re.IGNORECASE):
        return None

    # Try language-specific fenced blocks first, then generic
    patterns = [
        rf'```{re.escape(language)}\s*\n(.*?)```',      # ```python or ```cpp
        rf'```{re.escape("c++" if language == "cpp" else language)}\s*\n(.*?)```',
        r'```\w*\s*\n(.*?)```',                          # any fenced block
    ]

    for pattern in patterns:
        matches = re.findall(pattern, section_text, re.DOTALL)
        if matches:
            # Return the LAST code block (model may have revised)
            return matches[-1].strip()

    return None

def _split_into_sections(text: str, num_problems: int) -> dict[int, str]:
    """
    Split model output into per-problem sections.
    Mirrors the BigMath version but adapted for code problems.
    """
    sections = {}

    # Strategy 1: split on '## Problem K' headers
    header_pattern = r'##\s*Problem\s+(\d+)(.*?)(?=##\s*Problem\s+\d+|\Z)'
    matches = re.findall(header_pattern, text, re.DOTALL | re.IGNORECASE)

    if matches:
        for num_str, content in matches:
            idx = int(num_str) - 1  # 0-indexed
            if 0 <= idx < num_problems:
                sections[idx] = content.strip()
        if len(sections) >= max(1, num_problems // 2):
            return sections

    # Strategy 2: split on sequential code blocks
    code_pattern = r'```[\w+]*\s*\n.*?```'
    split_points = [(m.start(), m.end()) for m in re.finditer(code_pattern, text, re.DOTALL)]

    sections = {}
    prev_end = 0
    for i, (start, end) in enumerate(split_points):
        if i >= num_problems:
            break
        sections[i] = text[prev_end:end]
        prev_end = end

    return sections

def _score_single_cf_problem(
    source_code: str | None,
    ground_truth: dict,
    language: str = "python",
) -> float:
    """
    Score a single problem: run code against all available tests.
    Returns 1.0 if all tests pass, 0.0 otherwise.

    You could also return partial credit (passed/total) — see comment below.
    """
    if not source_code:
        return 0.0

    problem_id = ground_truth.get("id", "")
    tests = ground_truth.get("tests", [])
    checker = ground_truth.get("generated_checker")
    time_limit = ground_truth.get("time_limit")
    memory_limit = ground_truth.get("memory_limit")
    input_mode = ground_truth.get("input_mode", "stdio")

    # Append generated tests if available
    gen_tests = get_generated_tests(problem_id, max_tests=MAX_GENERATED_TESTS)
    all_tests = tests + gen_tests

    if not all_tests:
        # No tests available — can't verify. Return 0 to be safe,
        # or 0.5 if you want to give benefit of the doubt.
        return 0.0

    passed, total = _execute_solution_batch(
        source_code=source_code,
        tests=all_tests,
        language=language,
        time_limit=time_limit,
        memory_limit=memory_limit,
        input_mode=input_mode,
        generated_checker=checker,
        fail_fast=True,  # stop on first failure for speed
    )

    # Binary: 1.0 only if ALL tests pass
    return 1.0 if passed == total else 0.0

    # Alternative: partial credit per problem (uncomment if desired)
    # return passed / total if total > 0 else 0.0


def _store_solution_output(solution_str, ground_truth, extra_info, num_problems):
    """Store model output for debugging / analysis."""
    output_dir = "multi_problem_outputs_cf"
    os.makedirs(output_dir, exist_ok=True)

    if extra_info and "prompt_id" in extra_info:
        unique_id = extra_info["prompt_id"]
    elif extra_info and "index" in extra_info:
        unique_id = f"idx_{extra_info['index']}"
    else:
        gt_str = json.dumps(ground_truth, sort_keys=True) if not isinstance(ground_truth, str) else ground_truth
        unique_id = hashlib.md5(gt_str.encode()).hexdigest()[:12]

    safe_id = re.sub(r'[^\w\-]', '_', str(unique_id))
    filepath = os.path.join(output_dir, f"solution_{safe_id}.json")

    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "unique_id": unique_id,
        "num_problems": num_problems,
        "solution_str": solution_str,
        "ground_truth": ground_truth,
        "extra_info": extra_info,
    }

    lock_path = filepath + ".lock"
    try:
        with FileLock(lock_path, timeout=10):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[cf_reward] Warning: failed to store output to {filepath}: {e}")

def compute_score_codeforces(
    solution_str: str,
    ground_truth: str,
    extra_info: dict | None = None,
) -> float:
    """
    CodeForces reward function.

    Single-problem mode: returns 0.0 or 1.0
    Multi-problem mode:  returns (num_correct / num_problems)

    Detected via extra_info["num_problems"].
    """
    num_problems = (extra_info or {}).get("num_problems", None)

    if num_problems is None or num_problems <= 1:
        return _score_single_cf(solution_str, ground_truth, extra_info)

    return _score_multi_cf(solution_str, ground_truth, extra_info, num_problems)


def _score_single_cf(
    solution_str: str,
    ground_truth: str,
    extra_info: dict | None,
) -> float:
    """Single-problem CodeForces scoring."""
    language = (extra_info or {}).get("language", "python")

    # Parse ground truth
    if isinstance(ground_truth, str):
        try:
            gt = json.loads(ground_truth)
        except (json.JSONDecodeError, TypeError):
            return 0.0
    else:
        gt = ground_truth

    # If gt is a list (from multi-format), take first
    if isinstance(gt, list):
        gt = gt[0] if gt else {}

    source_code = _extract_code_from_section(solution_str, language)
    return _score_single_cf_problem(source_code, gt, language)


def _score_multi_cf(
    solution_str: str,
    ground_truth: str,
    extra_info: dict | None,
    num_problems: int,
) -> float:
    """
    Multi-problem CodeForces scoring.
    Parse each '## Problem K' section, extract code, execute against tests.
    Return fraction of problems solved correctly.
    """
    _store_solution_output(solution_str, ground_truth, extra_info, num_problems)

    # ── 1) Recover ground-truth list ──
    if extra_info and "ground_truths" in extra_info.get("tools_kwargs", {}):
        gt_list = extra_info["tools_kwargs"]["ground_truths"]
    elif isinstance(ground_truth, str):
        try:
            gt_list = json.loads(ground_truth)
        except (json.JSONDecodeError, TypeError):
            gt_list = [ground_truth]
    elif isinstance(ground_truth, list):
        gt_list = ground_truth
    else:
        gt_list = [ground_truth]

    num_problems = len(gt_list)
    if num_problems == 0:
        return 0.0

    language = (extra_info or {}).get("language", "python")
    if not language:
        language = (extra_info or {}).get("tools_kwargs", {}).get("language", "python")

    # ── 2) Extract per-problem sections from model output ──
    model_sections = _split_into_sections(solution_str, num_problems)

    # ── 3) Score each problem ──
    correct = 0
    details = []

    for i in range(num_problems):
        section_text = model_sections.get(i, "")
        source_code = _extract_code_from_section(section_text, language)

        gt = gt_list[i]
        if isinstance(gt, str):
            try:
                gt = json.loads(gt)
            except (json.JSONDecodeError, TypeError):
                details.append({"problem": i + 1, "correct": False, "reason": "bad_gt"})
                continue

        if not source_code:
            details.append({"problem": i + 1, "correct": False, "reason": "no_code"})
            continue

        score = _score_single_cf_problem(source_code, gt, language)
        is_correct = score >= 1.0

        if is_correct:
            correct += 1
        details.append({"problem": i + 1, "correct": is_correct})

    reward = correct / num_problems

    # Uncomment for debugging:
    # print(f"[cf_multi_reward] {correct}/{num_problems} = {reward:.3f} | {details}")

    return reward

def verl_reward_func(
   data_source: str,
   solution_str: str,
   ground_truth: str,
   extra_info: dict,
    ):
    if data_source in ["Maxwell-Jia/AIME_2024", "opencompass/cnmo2024_en", "opencompass/cnmo2024_zh"]:
        return compute_score_aime(solution_str, ground_truth)
    elif data_source == "Idavidrein/gpqa":
        return compute_score_gpqa(solution_str, ground_truth)
    elif data_source == "open-r1/Big-Math-RL-Verified-Processed":
        return compute_score_bigmath(solution_str, ground_truth, extra_info)
    elif data_source == "open-r1/codeforces":
        return compute_score_codeforces(solution_str, ground_truth, extra_info)
    else:
        raise NotImplementedError

def compute_score_bigmath(solution_str, ground_truth, extra_info):
    """
    Big-Math reward function.
    
    Single-problem mode: returns 0.0 or 1.0 (existing behavior).
    Multi-problem mode:  returns (num_correct / num_problems).
    
    Detected automatically via extra_info["num_problems"].
    """

    num_problems = (extra_info or {}).get("num_problems", None)

    # ── Single-problem path (original behavior, untouched) ──
    if num_problems is None or num_problems <= 1:
        return _score_single(solution_str, ground_truth, extra_info)

    # ── Multi-problem path ──
    return _score_multi(solution_str, ground_truth, extra_info, num_problems)

def _score_single(solution_str, ground_truth, extra_info):
    gold_text = _extract_gold_text(ground_truth)
    if not gold_text:
        return 0.0

    gold_parsed = parse(gold_text, extraction_mode="first_match", parsing_timeout=None)
    if not gold_parsed:
        return 0.0

    answer_parsed = _parse_model_answer(solution_str)
    if not answer_parsed:
        return 0.0

    try:
        reward = float(verify(gold_parsed, answer_parsed, timeout_seconds=None))
    except Exception as e:
        print(f"Big Math verify failed: {e}")
        reward = 0.0

    return 1.0 if reward > 0.0 else 0.0

def _score_multi(solution_str, ground_truth, extra_info, num_problems):
    """
    Parse each '## Problem K' section, compare to its ground truth.
    Return fraction correct.
    """
    _store_solution_output(solution_str, ground_truth, extra_info, num_problems)

    # ---- 1) Recover the list of ground-truth solutions ----
    if extra_info and "solutions" in extra_info:
        gt_list = extra_info["solutions"]
    elif isinstance(ground_truth, str):
        try:
            gt_list = json.loads(ground_truth)
        except (json.JSONDecodeError, TypeError):
            gt_list = [ground_truth]
    else:
        gt_list = [ground_truth]

    num_problems = len(gt_list)
    if num_problems == 0:
        return 0.0

    # ---- 2) Extract per-problem sections from model output ----
    model_sections = _split_into_sections(solution_str, num_problems)

    # ---- 3) Score each problem independently ----
    correct = 0
    details = []  # for debugging

    for i in range(num_problems):
        section_text = model_sections.get(i, "")
        gold_text = _extract_gold_text(gt_list[i])

        if not gold_text or not section_text:
            details.append({"problem": i + 1, "correct": False, "reason": "missing"})
            continue

        gold_parsed = parse(gold_text, extraction_mode="first_match", parsing_timeout=None)
        if not gold_parsed:
            details.append({"problem": i + 1, "correct": False, "reason": "gold_parse_fail"})
            continue

        answer_parsed = _parse_model_answer(section_text)
        if not answer_parsed:
            details.append({"problem": i + 1, "correct": False, "reason": "no_boxed"})
            continue

        try:
            is_correct = float(verify(gold_parsed, answer_parsed, timeout_seconds=None)) > 0.0
        except Exception as e:
            print(f"Big Math verify failed on problem {i+1}: {e}")
            is_correct = False

        if is_correct:
            correct += 1

        details.append({"problem": i + 1, "correct": is_correct})

    # ---- 4) Compute reward ----
    reward = correct / num_problems

    # Optional: uncomment for debugging during development
    # print(f"[multi-reward] {correct}/{num_problems} = {reward:.3f} | {details}")

    return reward


# ═══════════════════════════════════════════════════════════════
#  Shared helpers
# ═══════════════════════════════════════════════════════════════

def _extract_gold_text(ground_truth):
    """Normalize ground_truth into a plain string."""
    if isinstance(ground_truth, str):
        return ground_truth
    elif isinstance(ground_truth, dict):
        return (
            ground_truth.get("solution")
            or ground_truth.get("ground_truth")
            or ground_truth.get("answer")
            or ""
        )
    else:
        return str(ground_truth) if ground_truth is not None else ""


def _parse_model_answer(text):
    """Parse a model's boxed answer from a text chunk using math_verify."""
    return parse(
        text,
        extraction_config=[
            LatexExtractionConfig(
                normalization_config=NormalizationConfig(
                    nits=False,
                    malformed_operators=False,
                    basic_latex=True,
                    boxed="all",
                    units=True,
                ),
                boxed_match_priority=0,
                try_extract_without_anchor=False,
            )
        ],
        extraction_mode="first_match",
        parsing_timeout=None,
    )


def _split_into_sections(text: str, num_problems: int) -> dict[int, str]:
    """
    Split model output into per-problem sections.
    
    Tries two strategies:
      1. Header-based: '## Problem K' markers
      2. Fallback: sequential \boxed{} extraction (fragile but workable)
    
    Returns {0: "section text", 1: "section text", ...}
    """
    sections = {}

    # ── Strategy 1: split on '## Problem K' headers ──
    # Build regex that captures content between ## Problem K and ## Problem K+1 (or end)
    header_pattern = r'##\s*Problem\s+(\d+)(.*?)(?=##\s*Problem\s+\d+|\Z)'
    matches = re.findall(header_pattern, text, re.DOTALL | re.IGNORECASE)

    if matches:
        for num_str, content in matches:
            idx = int(num_str) - 1  # 0-indexed
            if 0 <= idx < num_problems:
                sections[idx] = content.strip()
        # If we found at least half the problems this way, trust it
        if len(sections) >= num_problems // 2:
            return sections

    # ── Strategy 2: fallback — split on sequential \boxed{} ──
    # Each boxed answer and its preceding work = one "section"
    boxed_pattern = r'\\boxed\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    split_points = [(m.start(), m.end()) for m in re.finditer(boxed_pattern, text)]

    sections = {}
    prev_end = 0
    for i, (start, end) in enumerate(split_points):
        if i >= num_problems:
            break
        # Section = everything from prev_end to this boxed answer's end
        sections[i] = text[prev_end:end]
        prev_end = end

    return sections

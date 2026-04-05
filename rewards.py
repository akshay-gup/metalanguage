"""Reward/scoring utilities for Hugging Face dataset rows.

This module keeps text-style rewards and adds coding-oriented rewards so it can
support a wider mix of datasets (classification, QA, math, and code).
"""

from __future__ import annotations

import ast
import json
import math
import re
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


RewardFn = Callable[[str, str], float]


@dataclass(frozen=True)
class ScoreResult:
    """Container for per-example scoring output."""

    score: float
    prediction: str
    reference: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_text(value: str) -> str:
    """Normalize text for robust comparisons."""

    normalized = value.lower().strip()
    return re.sub(r"\s+", " ", normalized)


def exact_match_reward(
    prediction: str,
    reference: str,
    *,
    normalize: bool = True,
    correct_reward: float = 1.0,
    incorrect_reward: float = 0.0,
) -> float:
    """Return `correct_reward` on exact match, else `incorrect_reward`."""

    if normalize:
        prediction = normalize_text(prediction)
        reference = normalize_text(reference)
    return correct_reward if prediction == reference else incorrect_reward


def contains_reward(
    prediction: str,
    reference: str,
    *,
    normalize: bool = True,
    correct_reward: float = 1.0,
    incorrect_reward: float = 0.0,
) -> float:
    """Return positive reward when the reference appears in prediction."""

    if normalize:
        prediction = normalize_text(prediction)
        reference = normalize_text(reference)
    return correct_reward if reference in prediction else incorrect_reward


def regex_reward(
    prediction: str,
    reference: str,
    *,
    flags: int = 0,
    correct_reward: float = 1.0,
    incorrect_reward: float = 0.0,
) -> float:
    """Treat reference as a regex pattern and score by match/no-match."""

    try:
        return correct_reward if re.search(reference, prediction, flags=flags) else incorrect_reward
    except re.error:
        return incorrect_reward


def numeric_tolerance_reward(
    prediction: str,
    reference: str,
    *,
    tolerance: float = 1e-6,
    correct_reward: float = 1.0,
    incorrect_reward: float = 0.0,
) -> float:
    """Score numeric outputs with an absolute tolerance."""

    try:
        pred_value = float(prediction)
        ref_value = float(reference)
    except (TypeError, ValueError):
        return incorrect_reward

    return correct_reward if math.isclose(pred_value, ref_value, abs_tol=tolerance) else incorrect_reward


def token_f1_reward(prediction: str, reference: str, *, normalize: bool = True) -> float:
    """Token-level F1 score in [0, 1], useful for short-form QA."""

    if normalize:
        prediction = normalize_text(prediction)
        reference = normalize_text(reference)

    pred_tokens = prediction.split()
    ref_tokens = reference.split()
    if not pred_tokens and not ref_tokens:
        return 1.0
    if not pred_tokens or not ref_tokens:
        return 0.0

    common: dict[str, int] = {}
    for token in ref_tokens:
        common[token] = common.get(token, 0) + 1

    overlap = 0
    for token in pred_tokens:
        count = common.get(token, 0)
        if count > 0:
            overlap += 1
            common[token] = count - 1

    if overlap == 0:
        return 0.0

    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def _extract_python_from_markdown(text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def python_syntax_reward(
    prediction: str,
    reference: str = "",
    *,
    correct_reward: float = 1.0,
    incorrect_reward: float = 0.0,
) -> float:
    """Score whether prediction contains syntactically valid Python."""

    code = _extract_python_from_markdown(prediction)
    try:
        ast.parse(code)
        return correct_reward
    except SyntaxError:
        return incorrect_reward


def python_unit_test_reward(
    prediction: str,
    reference: str,
    *,
    timeout_seconds: int = 3,
    correct_reward: float = 1.0,
    incorrect_reward: float = 0.0,
) -> float:
    """Run generated Python code against lightweight assertion tests.

    Reference supports either:
    - raw python assertions (e.g. ``assert add(1, 2) == 3``), or
    - JSON list of assertion lines.
    """

    code = _extract_python_from_markdown(prediction)
    tests = reference.strip()

    if tests.startswith("["):
        try:
            parsed = json.loads(tests)
            if isinstance(parsed, list):
                tests = "\n".join(str(item) for item in parsed)
        except json.JSONDecodeError:
            return incorrect_reward

    test_block = textwrap.indent(tests or "pass", "    ")
    harness = "\n\n".join(
        [
            code,
            "def __run_tests__():\n" + test_block,
            'if __name__ == "__main__":\n    __run_tests__()\n    print("OK")',
        ]
    ) + "\n"

    try:
        with tempfile.TemporaryDirectory(prefix="reward_eval_") as td:
            script = Path(td) / "candidate.py"
            script.write_text(harness, encoding="utf-8")
            proc = subprocess.run(
                ["python", str(script)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return incorrect_reward

    return correct_reward if proc.returncode == 0 else incorrect_reward


def weighted_reward(
    prediction: str,
    reference: str,
    *,
    components: Sequence[tuple[RewardFn, float]],
    normalize_weights: bool = True,
) -> float:
    """Compute weighted sum from multiple reward functions."""

    if not components:
        return 0.0

    total_weight = sum(weight for _, weight in components)
    if total_weight <= 0:
        return 0.0

    score = sum(fn(prediction, reference) * weight for fn, weight in components)
    return score / total_weight if normalize_weights else score


def make_hf_row_reward(
    *,
    prediction_key: str = "prediction",
    reference_key: str = "label",
    reward_fn: RewardFn | None = None,
    on_error_score: float = 0.0,
) -> Callable[[dict[str, Any]], ScoreResult]:
    """Build a row scorer for Hugging Face-style dictionaries."""

    if reward_fn is None:
        reward_fn = exact_match_reward

    def score_row(row: dict[str, Any]) -> ScoreResult:
        prediction = str(row[prediction_key])
        reference = str(row[reference_key])
        try:
            score = float(reward_fn(prediction, reference))
            return ScoreResult(score=score, prediction=prediction, reference=reference)
        except Exception as exc:  # defensive in data pipelines
            return ScoreResult(
                score=on_error_score,
                prediction=prediction,
                reference=reference,
                error=str(exc),
            )

    return score_row


def score_rows(
    rows: Iterable[dict[str, Any]],
    *,
    prediction_key: str = "prediction",
    reference_key: str = "label",
    reward_fn: RewardFn | None = None,
    on_error_score: float = 0.0,
) -> list[ScoreResult]:
    """Score an iterable of rows and return per-example results."""

    scorer = make_hf_row_reward(
        prediction_key=prediction_key,
        reference_key=reference_key,
        reward_fn=reward_fn,
        on_error_score=on_error_score,
    )
    return [scorer(row) for row in rows]


def mean_score(results: Iterable[ScoreResult]) -> float:
    """Compute average score, returning 0.0 for empty input."""

    results_list = list(results)
    if not results_list:
        return 0.0
    return sum(item.score for item in results_list) / len(results_list)


REWARD_REGISTRY: dict[str, RewardFn] = {
    "exact_match": exact_match_reward,
    "contains": contains_reward,
    "regex": regex_reward,
    "numeric_tolerance": numeric_tolerance_reward,
    "token_f1": token_f1_reward,
    "python_syntax": python_syntax_reward,
    "python_unit_test": python_unit_test_reward,
}

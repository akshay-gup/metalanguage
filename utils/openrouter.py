"""OpenRouter Responses API utility with function-tool support."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal
import time
import requests


OPENROUTER_RESPONSES_URL = "https://openrouter.ai/api/v1/responses"
ToolChoice = Literal["auto", "none"] | dict[str, str]
RetryCallback = Callable[[dict[str, Any]], None]
RETRYABLE_REQUEST_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.SSLError,
    requests.exceptions.Timeout,
)


def _retry_delay_seconds(attempt: int, initial_delay: float, max_delay: float) -> float:
    return min(max_delay, initial_delay * (2 ** max(0, attempt - 1)))


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _parse_error_body(response: requests.Response) -> dict[str, Any] | str:
    try:
        return response.json()
    except ValueError:
        return response.text


class OpenRouterAPIError(RuntimeError):
    """Structured OpenRouter API error."""

    def __init__(self, status_code: int, response_body: dict[str, Any] | str):
        self.status_code = status_code
        self.response_body = response_body
        if isinstance(response_body, dict):
            error = response_body.get("error")
            if isinstance(error, dict):
                self.error_code = error.get("code")
                self.message = str(error.get("message") or "")
                self.metadata = error.get("metadata")
            else:
                self.error_code = None
                self.message = str(response_body)
                self.metadata = None
        else:
            self.error_code = None
            self.message = response_body
            self.metadata = None
        super().__init__(f"OpenRouter API request failed ({status_code}): {self.message}")


def call_openrouter_with_tools(
    *,
    api_key: str,
    model: str,
    input_items: list[dict[str, Any]] | str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: ToolChoice = "auto",
    max_output_tokens: int | None = None,
    stream: bool = False,
    timeout: int = 60,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    max_retries: int = 5,
    retry_initial_delay: float = 1.0,
    retry_max_delay: float = 10.0,
    retry_callback: RetryCallback | None = None,
) -> dict[str, Any] | requests.Response:
    """Call OpenRouter's Responses API with optional function tools.

    Returns parsed JSON for standard requests and a streaming `requests.Response`
    when `stream=True`.
    """
    payload: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "stream": stream,
    }

    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens

    if tools is not None:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}

    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                OPENROUTER_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
                stream=stream,
            )
        except RETRYABLE_REQUEST_EXCEPTIONS as exc:
            if attempt >= max_retries:
                raise
            delay_seconds = _retry_delay_seconds(
                attempt + 1,
                retry_initial_delay,
                retry_max_delay,
            )
            if retry_callback is not None:
                retry_callback(
                    {
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "delay_seconds": delay_seconds,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    }
                )
            time.sleep(delay_seconds)
            continue

        if response.ok:
            if stream:
                return response
            return response.json()

        response_body = _parse_error_body(response)
        if _is_retryable_status(response.status_code) and attempt < max_retries:
            delay_seconds = _retry_delay_seconds(
                attempt + 1,
                retry_initial_delay,
                retry_max_delay,
            )
            if retry_callback is not None:
                retry_callback(
                    {
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "delay_seconds": delay_seconds,
                        "status_code": response.status_code,
                        "error_type": "OpenRouterAPIError",
                        "error_message": str(response_body),
                    }
                )
            response.close()
            time.sleep(delay_seconds)
            continue

        raise OpenRouterAPIError(response.status_code, response_body)

    raise RuntimeError("OpenRouter retry loop exhausted unexpectedly.")


def get_tool_calls(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract valid function-call items from an OpenRouter response JSON."""
    output_items = response_json.get("output", [])
    if not isinstance(output_items, list):
        return []

    tool_calls: list[dict[str, Any]] = []
    for item in output_items:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue

        required_fields = ("id", "call_id", "name", "arguments")
        if all(field in item for field in required_fields):
            tool_calls.append(item)

    return tool_calls


bash_tool: dict[str, Any] = {
    "type": "function",
    "name": "run_bash",
    "description": "Run a bash command in a controlled environment and return stdout/stderr.",
    "strict": None,
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Bash command to execute, e.g. 'ls -la'.",
            },
            "working_directory": {
                "type": "string",
                "description": "Optional working directory for command execution.",
            },
        },
        "required": ["command"],
    },
}


budget_status_tool: dict[str, Any] = {
    "type": "function",
    "name": "budget_status",
    "description": "Return this rollout's token budget, spent tokens, reserved/spent continuation budget, transfers, remaining budget, and minimum_child_budget_tokens.",
    "strict": None,
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


submit_solution_tool: dict[str, Any] = {
    "type": "function",
    "name": "submit_solution",
    "description": (
        "Submit a problem uuid from the shared workspace problem pool and its answer for immediate scoring. The response "
        "returns correct/incorrect, reward, credited tokens, and updated budget."
    ),
    "strict": None,
    "parameters": {
        "type": "object",
        "properties": {
            "uuid": {
                "type": "string",
                "description": "Problem uuid copied from shared_workspace/problem_pool.json or shared_workspace/problem_pool.md.",
            },
            "answer": {
                "type": "string",
                "description": "Answer to score against the selected problem uuid.",
            },
        },
        "required": ["uuid", "answer"],
    },
}


transfer_tokens_tool: dict[str, Any] = {
    "type": "function",
    "name": "transfer_tokens",
    "description": (
        "Move token budget from this rollout to a live same-task peer. "
        "The target's budget increases by exactly amount_tokens."
    ),
    "strict": None,
    "parameters": {
        "type": "object",
        "properties": {
            "target_instance_uuid": {
                "type": "string",
                "description": "Instance UUID of a live peer rollout listed in runtime.md.",
            },
            "amount_tokens": {
                "type": "integer",
                "description": "Positive token budget amount to transfer.",
            },
        },
        "required": ["target_instance_uuid", "amount_tokens"],
    },
}


spawn_child_tool: dict[str, Any] = {
    "type": "function",
    "name": "spawn_child",
    "description": (
        "Competitively claim a next-iteration rollout slot by passing the child's "
        "inherited prompt, optionally copying a workspace-local directory into "
        "the child workspace, and reserving exactly initial_budget_tokens from "
        "this rollout. initial_budget_tokens must be at least the runtime "
        "minimum_child_budget_tokens. Slots are first-come first-served; one "
        "rollout may claim multiple slots, and calls fail without reserving "
        "budget after the task slot cap is full."
    ),
    "strict": None,
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Required non-empty initial prompt for the child rollout. Include the durable core instructions needed to solve, submit_solution, use archive/shared_workspace, and spawn again.",
            },
            "workspace_dir": {
                "type": "string",
                "description": "Optional workspace-local directory whose contents should be copied into the child rollout root. Leave blank or omit for no inherited workspace files.",
            },
            "initial_budget_tokens": {
                "type": "integer",
                "description": "Token budget to reserve from this rollout and assign exactly to the claimed slot. Must be at least minimum_child_budget_tokens from runtime.md.",
            },
        },
        "required": ["prompt", "initial_budget_tokens"],
    },
}

"""OpenRouter Responses API utility with function-tool support."""

from __future__ import annotations

from typing import Any, Literal
import requests


OPENROUTER_RESPONSES_URL = "https://openrouter.ai/api/v1/responses"
ToolChoice = Literal["auto", "none"] | dict[str, str]


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

    if not response.ok:
        try:
            response_body: dict[str, Any] | str = response.json()
        except ValueError:
            response_body = response.text
        raise OpenRouterAPIError(response.status_code, response_body)

    if stream:
        return response

    return response.json()


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

"""Utility helpers for chat-completions-compatible APIs."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request


def _normalize_base_url(base_url: str) -> str:
    """Normalize a base URL so endpoint paths can be appended safely."""
    return base_url.rstrip("/")


def _extract_text_content(message: dict[str, Any]) -> str:
    """Extract text from a chat message content field.

    Supports either a plain string or the structured list format used by
    chat-completions APIs.
    """
    content = message.get("content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)

    return ""


def chat_text(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    timeout: float = 30.0,
    endpoint: str = "/v1/chat/completions",
    extra_payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> str:
    """Send chat messages to a compatible API and return assistant text.

    Args:
        base_url: API base URL.
        api_key: Bearer token for authorization.
        model: Model id to use for completion.
        messages: Chat messages list with ``role`` and ``content``.
        temperature: Sampling temperature.
        timeout: Request timeout in seconds.
        endpoint: Chat completions endpoint path.
        extra_payload: Optional additional JSON fields.
        extra_headers: Optional additional HTTP headers.

    Returns:
        The first assistant choice content as plain text.

    Raises:
        ValueError: If required fields are missing.
        RuntimeError: If the API response cannot be parsed as expected.
        urllib.error.HTTPError: If the API returns an HTTP error status.
        urllib.error.URLError: If connection fails.
    """
    if not base_url:
        raise ValueError("base_url is required")
    if not api_key:
        raise ValueError("api_key is required")
    if not model:
        raise ValueError("model is required")
    if not messages:
        raise ValueError("messages is required")
    if not endpoint:
        raise ValueError("endpoint is required")

    url = f"{_normalize_base_url(base_url)}{endpoint}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if extra_payload:
        payload.update(extra_payload)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)

    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise error.HTTPError(
            exc.url,
            exc.code,
            f"{exc.reason}: {detail}",
            exc.headers,
            exc.fp,
        ) from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Response missing choices")

    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("Unexpected choice format")

    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Response missing message")

    return _extract_text_content(message)

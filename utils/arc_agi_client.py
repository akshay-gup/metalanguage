"""Thin stdlib client for an official ARC-AGI server on loopback."""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_LOCAL_TOKEN = "metalanguage-local"
ACTION_NAMES = {"RESET", *(f"ACTION{number}" for number in range(1, 8))}


class ArcAgiClientError(RuntimeError):
    """Base error for local ARC client failures."""


class ArcAgiHttpError(ArcAgiClientError):
    """A non-success response from the local ARC server."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        self.method = method
        self.path = path
        self.status = status
        self.body = body
        super().__init__(f"ARC request {method} {path} failed ({status}): {body}")


class ArcAgiProtocolError(ArcAgiClientError):
    """The local ARC server returned an unexpected response."""


class ArcAgiTransportError(ArcAgiClientError):
    """The local ARC server could not be reached."""


class ArcAgiClient:
    """Client for one loopback ARC server, with persistent cookie handling."""

    def __init__(
        self,
        base_url: str,
        *,
        client_token: str = DEFAULT_LOCAL_TOKEN,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        if not client_token or "\r" in client_token or "\n" in client_token:
            raise ValueError("client_token must be non-empty and contain no newlines")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._client_token = client_token
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
        )

    def list_games(self) -> list[dict[str, Any]]:
        games = self._request("GET", "/api/games", expected=list)
        if not all(isinstance(game, dict) for game in games):
            raise ArcAgiProtocolError("GET /api/games returned a non-object game")
        return games

    def open_scorecard(
        self,
        *,
        tags: list[str] | None = None,
        opaque: Any = None,
        source_url: str | None = None,
    ) -> str:
        if tags is not None and not all(isinstance(tag, str) for tag in tags):
            raise ValueError("tags must contain only strings")
        payload: dict[str, Any] = {}
        if tags is not None:
            payload["tags"] = tags
        if opaque is not None:
            payload["opaque"] = opaque
        if source_url is not None:
            payload["source_url"] = source_url
        response = self._request(
            "POST", "/api/scorecard/open", payload, expected=dict
        )
        card_id = response.get("card_id")
        if not isinstance(card_id, str) or not card_id:
            raise ArcAgiProtocolError("scorecard open response has no card_id")
        return card_id

    def reset(
        self,
        card_id: str,
        game_id: str,
        *,
        guid: str | None = None,
        reasoning: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "card_id": _require_id("card_id", card_id),
            "game_id": _require_id("game_id", game_id),
        }
        if guid is not None:
            payload["guid"] = _require_id("guid", guid)
        if reasoning is not None:
            payload["reasoning"] = reasoning
        return self._frame_request("RESET", payload)

    start_game = reset

    def step(
        self,
        game_id: str,
        guid: str,
        action: str | int,
        *,
        x: int | None = None,
        y: int | None = None,
        reasoning: Any = None,
    ) -> dict[str, Any]:
        action_name = _normalize_action(action)
        if action_name == "ACTION6":
            _validate_coordinate("x", x)
            _validate_coordinate("y", y)
        elif x is not None or y is not None:
            raise ValueError("x/y are only valid for ACTION6")

        payload: dict[str, Any] = {
            "game_id": _require_id("game_id", game_id),
            "guid": _require_id("guid", guid),
        }
        if action_name == "ACTION6":
            payload.update(x=x, y=y)
        if reasoning is not None:
            payload["reasoning"] = reasoning
        return self._frame_request(action_name, payload)

    def get_scorecard(
        self, card_id: str, game_id: str | None = None
    ) -> dict[str, Any]:
        path = f"/api/scorecard/{_quote_id('card_id', card_id)}"
        if game_id is not None:
            path += f"/{_quote_id('game_id', game_id)}"
        return self._request("GET", path, expected=dict)

    def close_scorecard(self, card_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/scorecard/close",
            {"card_id": _require_id("card_id", card_id)},
            expected=dict,
        )

    def _frame_request(
        self, action_name: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        response = self._request(
            "POST", f"/api/cmd/{action_name}", payload, expected=dict
        )
        if not isinstance(response.get("guid"), str) or not response["guid"]:
            raise ArcAgiProtocolError(f"{action_name} response has no guid")
        if not isinstance(response.get("frame"), list):
            raise ArcAgiProtocolError(f"{action_name} response has no frame list")
        actions = response.get("available_actions")
        if not isinstance(actions, list) or not all(
            isinstance(item, int) and 0 <= item <= 7 for item in actions
        ):
            raise ArcAgiProtocolError(
                f"{action_name} response has invalid available_actions"
            )
        return response

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: type[dict] | type[list],
    ) -> Any:
        data = None
        headers = {"Accept": "application/json", "X-API-Key": self._client_token}
        if payload is not None:
            try:
                data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ValueError("request payload must be JSON-serializable") from exc
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            raise ArcAgiHttpError(
                method, path, exc.code, self._safe_body(raw)
            ) from None
        except (OSError, TimeoutError, urllib.error.URLError):
            raise ArcAgiTransportError(
                f"ARC request {method} {path} could not reach the loopback server"
            ) from None
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ArcAgiProtocolError(
                f"ARC request {method} {path} returned invalid JSON"
            ) from None
        if not isinstance(decoded, expected):
            raise ArcAgiProtocolError(
                f"ARC request {method} {path} returned {type(decoded).__name__}, "
                f"expected {expected.__name__}"
            )
        return decoded

    def _safe_body(self, raw: bytes) -> str:
        text = raw.decode("utf-8", errors="replace")[:1000]
        return text.replace(self._client_token, "<redacted>")


def _validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an HTTP loopback origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("base_url has an invalid port") from exc
    if port is None:
        raise ValueError("base_url must include a port")
    return f"http://{parsed.hostname}:{port}"


def _require_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _quote_id(name: str, value: str) -> str:
    return urllib.parse.quote(_require_id(name, value), safe="")


def _normalize_action(action: str | int) -> str:
    if isinstance(action, bool):
        raise ValueError("action must be RESET or ACTION1..ACTION7")
    if isinstance(action, int):
        action = "RESET" if action == 0 else f"ACTION{action}"
    if not isinstance(action, str) or action.upper() not in ACTION_NAMES:
        raise ValueError("action must be RESET or ACTION1..ACTION7")
    return action.upper()


def _validate_coordinate(name: str, value: int | None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 63:
        raise ValueError(f"{name} must be an integer from 0 through 63")

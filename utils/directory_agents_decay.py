"""Versioned opt-in policy; legacy runtimes have no decay identity file."""

import json
from pathlib import Path


IDENTITY_FILE = "directory_agents_policy.json"


def validate_policy(mode: str, steps: int | None, backends: set[str]) -> None:
    if mode not in {"cumulative", "decay"}:
        raise ValueError("unknown directory AGENTS mode")
    if mode == "cumulative":
        if steps is not None:
            raise ValueError("decay steps require --directory-agents-mode decay")
        return
    if type(steps) is not int or not 1 <= steps <= 2**64 - 1:
        raise ValueError("decay mode requires a positive --directory-agents-decay-steps K")
    if backends != {"codex"}:
        raise ValueError("directory AGENTS decay is supported only by managed Codex")


def claim_policy(root: Path, mode: str, steps: int | None, *, was_empty: bool) -> None:
    """Reject migration, policy changes, and corrupt identity before any rollout."""
    path = root / IDENTITY_FILE
    expected = {"schema": 1, "mode": mode, "steps": steps}
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != expected:
            raise ValueError("directory AGENTS policy changed; use a fresh runtime root")
    elif mode == "decay":
        if not was_empty:
            raise ValueError("directory AGENTS decay requires a fresh runtime root")
        # Exclusive creation: never overwrite an identity from another launcher.
        with path.open("x", encoding="utf-8") as output:
            json.dump(expected, output, sort_keys=True)
            output.write("\n")

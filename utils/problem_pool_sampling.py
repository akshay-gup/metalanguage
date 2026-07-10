"""Deterministic sampling for already-filtered problem-pool candidates."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import TypeVar

RecordT = TypeVar("RecordT")


def deterministic_problem_pool_sample(
    records: Sequence[RecordT],
    *,
    problem_pool_size: int | None,
    seed: int,
    iteration_index: int,
    record_id: Callable[[RecordT], str],
) -> list[RecordT]:
    """Return a reproducible capped sample of already-filtered candidates.

    Filtering solved or otherwise ineligible records belongs to the caller. The
    configured seed, actual iteration index, and each stable record identifier
    determine sample membership without relying on Python's randomized hash().
    """

    if problem_pool_size is None:
        return list(records)
    if problem_pool_size <= 0:
        raise ValueError("problem_pool_size must be > 0 when set")
    if len(records) <= problem_pool_size:
        return list(records)

    ranked: list[tuple[bytes, str, RecordT]] = []
    seen_ids: set[str] = set()
    for record in records:
        identifier = record_id(record)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("problem-pool record identifiers must be non-empty strings")
        if identifier in seen_ids:
            raise ValueError(f"duplicate problem-pool record identifier: {identifier}")
        seen_ids.add(identifier)
        digest = hashlib.sha256(
            b"metalanguage/problem-pool/v1\0"
            + str(seed).encode("utf-8")
            + b"\0"
            + str(iteration_index).encode("utf-8")
            + b"\0"
            + identifier.encode("utf-8")
        ).digest()
        ranked.append((digest, identifier, record))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [record for _, _, record in ranked[:problem_pool_size]]

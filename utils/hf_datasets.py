"""Utilities for downloading Hugging Face datasets to local files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets import load_dataset


def download_hf_dataset_to_file(
    *,
    dataset_name: str,
    output_path: str,
    split: str = "train",
    config_name: str | None = None,
    max_rows: int | None = None,
    streaming: bool = False,
    **load_dataset_kwargs: Any,
) -> Path:
    """Download a Hugging Face dataset split and write it as JSONL.

    Args:
        dataset_name: Hugging Face dataset id, e.g. ``"ag_news"``.
        output_path: Destination JSONL file path.
        split: Dataset split name. Defaults to ``"train"``.
        config_name: Optional dataset config/subset name.
        max_rows: Optional row cap written to disk.
        streaming: Whether to use streaming mode when loading.
        **load_dataset_kwargs: Additional kwargs forwarded to ``load_dataset``.

    Returns:
        The resolved output ``Path``.
    """
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset(
        path=dataset_name,
        name=config_name,
        split=split,
        streaming=streaming,
        **load_dataset_kwargs,
    )

    written = 0
    with destination.open("w", encoding="utf-8") as fh:
        for row in dataset:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            if max_rows is not None and written >= max_rows:
                break

    return destination.resolve()

"""Utilities for downloading and serving Hugging Face datasets."""

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


class HFDatasetDataLoader:
    """Simple batch data loader backed by a Hugging Face dataset split.

    This class is intentionally framework-agnostic so it can be used with
    PyTorch, JAX, or custom training loops.
    """

    def __init__(
        self,
        *,
        dataset_name: str,
        split: str = "train",
        config_name: str | None = None,
        batch_size: int = 32,
        shuffle: bool = True,
        seed: int = 42,
        streaming: bool = False,
        drop_last: bool = False,
        transform: Any | None = None,
        **load_dataset_kwargs: Any,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")

        self.batch_size = batch_size
        self.drop_last = drop_last
        self.transform = transform
        self.streaming = streaming

        self.dataset = load_dataset(
            path=dataset_name,
            name=config_name,
            split=split,
            streaming=streaming,
            **load_dataset_kwargs,
        )

        if shuffle:
            if streaming:
                self.dataset = self.dataset.shuffle(buffer_size=10_000, seed=seed)
            else:
                self.dataset = self.dataset.shuffle(seed=seed)

    def __iter__(self):
        batch: list[dict[str, Any]] = []
        for row in self.dataset:
            item = self.transform(row) if self.transform else row
            batch.append(item)
            if len(batch) == self.batch_size:
                yield batch
                batch = []

        if batch and not self.drop_last:
            yield batch

    def __len__(self) -> int:
        if self.streaming:
            raise TypeError("Length is not available for streaming datasets.")

        dataset_len = len(self.dataset)
        if self.drop_last:
            return dataset_len // self.batch_size

        return (dataset_len + self.batch_size - 1) // self.batch_size

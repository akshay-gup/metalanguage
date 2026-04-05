# metalanguage

Open ended RSI

## Utilities

- `utils/reward.py`: reward/evaluation helpers used by training workflows.
- `utils/openrouter.py`: helpers for OpenRouter Responses API calls.
- `utils/hf_datasets.py`:
  - `download_hf_dataset_to_file(...)` writes a Hugging Face dataset split to JSONL.
  - `HFDatasetDataLoader(...)` pulls dataset rows and yields mini-batches for training loops.

## Episode runner

- `main_loop.py`: runs one RLVR-style episode end-to-end:
  1. sample one task from HF dataset,
  2. create ephemeral temp workspace and write task.json,
  3. run OpenRouter worker with `run_bash` tool access to produce `solution.md`,
  4. score solution via `utils/reward.py`,
  5. append run metadata to a growing JSONL log,
  6. print one-line summary.


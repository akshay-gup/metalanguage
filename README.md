# metalanguage

Open ended RSI

## Utilities

- `utils/openrouter.py`: helpers for OpenRouter Responses API calls.
- `utils/hf_datasets.py`:
  - `download_hf_dataset_to_file(...)` writes a Hugging Face dataset split to JSONL.
  - `HFDatasetDataLoader(...)` pulls dataset rows and yields mini-batches for training loops.

- `rewards.py`:
  - reward/scoring helpers for Hugging Face-style rows, including text rewards and coding rewards (`python_syntax_reward`, `python_unit_test_reward`).

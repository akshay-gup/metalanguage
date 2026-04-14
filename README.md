# metalanguage

Open ended RSI

## Utilities

- `utils/reward.py`: reward/evaluation helpers used by training workflows.
- `utils/openrouter.py`: helpers for OpenRouter Responses API calls.
- `utils/hf_datasets.py`:
  - `download_hf_dataset_to_file(...)` writes a Hugging Face dataset split to JSONL.
  - `HFDatasetDataLoader(...)` pulls dataset rows and yields mini-batches for training loops.

## Episode runner

- `main_loop.py`: runs RLVR-style episodes end-to-end:
  1. by default, sample one task from HF dataset (or process all tasks with `--all-tasks`),
  2. run `--num-rollouts` child rollouts per task in isolated temp workspaces (each with an auto-assigned unique rollout username),
  3. sample each child's parent (with replacement) from the prior task's successful rollouts,
  4. run OpenRouter worker with `run_bash` tool access to produce `solution.md`,
  5. score solution via `utils/reward.py`,
  6. retain only successful rollout workspaces as parent candidates for the next task,
  7. append run metadata to a growing JSONL log and print one-line summary per rollout.
- Resume behavior:
  - runs automatically resume from existing `--runs-log` entries that match dataset/split/model/seed/generation/config/rollout-count;
  - completed rollouts are skipped, partial tasks continue from missing rollout indices;
  - parent lineage candidates are persisted under `--rollout-temp-root/latest_parent_pool.json`, so resume restores the exact parent pool without replaying old tasks;
  - disable this with `--no-resume`.

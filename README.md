# metalanguage

Open ended RSI

## Utilities

- `utils/reward.py`: reward/evaluation helpers used by training workflows.
- `utils/openrouter.py`: helpers for OpenRouter Responses API calls.
- `utils/task_store.py`: task-store persistence/redaction and rollout answer artifact helpers.
- `utils/hf_datasets.py`:
  - `download_hf_dataset_to_file(...)` writes a Hugging Face dataset split to JSONL.
  - `HFDatasetDataLoader(...)` pulls dataset rows and yields mini-batches for training loops.

## Episode runner

- `main_loop.py`: runs RLVR-style episodes end-to-end:
  1. by default, sample one task from HF dataset (or process all tasks with `--all-tasks`),
  2. run `--num-rollouts` child rollouts per task in isolated temp workspaces (each with an auto-assigned unique rollout username),
  3. sample each child's parent (with replacement) from the prior task's successful rollouts,
  4. write the original dataset row as-is under `--task-store-dir`, while model-visible workspace task files redact solution-like fields,
  5. run OpenRouter worker with `run_bash` tool access to produce `solution.json` (`problem_uid` + `task_id` + `answer`, with `solution.md` fallback),
  6. score solution via `utils/reward.py`, grounding correctness against the private stored row and validating reported ids,
  7. retain only successful rollout workspaces as parent candidates for the next task,
  8. append run metadata to a growing JSONL log and print one-line summary per rollout.
- Parent allotment strategies:
  - default `--parent-allotment round_robin` preserves existing behavior by sampling uniformly from successful parents;
  - `--parent-allotment solved_proportional` weights by `max(1, solved_count)` so rollouts that have solved more prior tasks are allotted more often.
- Resume behavior:
  - runs automatically resume from existing `--runs-log` entries that match dataset/split/model/seed/generation/config/rollout-count;
  - completed rollouts are skipped, partial tasks continue from missing rollout indices;
  - parent lineage candidates are persisted under `--rollout-temp-root/latest_parent_pool.json`, so resume restores the exact parent pool without replaying old tasks;
  - disable this with `--no-resume`.

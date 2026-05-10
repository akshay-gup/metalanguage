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
  3.5. expose a shared cross-rollout workspace at `--rollout-temp-root/shared_workspace` where any rollout agent can leave files/messages for any other rollout agent (files written by each rollout are cleaned up after that rollout ends),
  4. expose `archive/world_repo` by default as the durable cross-lineage Git archive available to every rollout (override with `--archive-repo-dir`),
  5. write the original dataset row as-is under `--task-store-dir`, while model-visible workspace task files redact solution-like fields,
  6. run OpenRouter worker with `run_bash` tool access to produce `solution.json` (`problem_uid` + `task_id` + `answer`, with `solution.md` fallback),
     while allowing access to the current workspace, parent rollout seed, next rollout seed, shared workspace, and archive repo,
  7. score solution via `utils/reward.py`, grounding correctness against the private stored row and validating reported ids,
  8. retain only successful rollout workspaces as parent candidates for the next task,
  9. append run metadata to a growing JSONL log and print one-line summary per rollout.
- Resume behavior:
  - runs automatically resume from existing `--runs-log` entries that match dataset/split/model/seed/generation/config/rollout-count;
  - completed rollouts are skipped, partial tasks continue from missing rollout indices;
  - parent lineage candidates are persisted under `--rollout-temp-root/latest_parent_pool.json`, so resume restores the exact parent pool without replaying old tasks;
  - disable this with `--no-resume`.

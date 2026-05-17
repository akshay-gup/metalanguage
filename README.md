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
  1. by default, sample one task from `m-a-p/SuperGPQA` (or process all tasks with `--all-tasks`; override with `--dataset-name`),
  2. run `--num-rollouts` child rollouts per task concurrently in isolated temp workspaces (each with an auto-assigned unique rollout username),
  3. sample each child's parent (with replacement) from the prior task's successful rollouts,
  3.5. expose a shared cross-rollout workspace at `--rollout-temp-root/shared_workspace` where any rollout agent can leave files/messages for any other rollout agent (files written by each rollout are cleaned up after that rollout ends),
  4. expose `archive/world_repo` by default as the durable cross-lineage Git archive available to every rollout (override with `--archive-repo-dir`),
     using a per-rollout temporary worktree so only committed archive changes are merged back and uncommitted archive edits are discarded,
  5. copy the selected parent seed workspace into the child workspace, then write the current task as `task.md` with solution-like fields redacted,
  6. run OpenRouter worker with `run_bash` tool access and a minimal fixed prompt that only provides the working directory; operating doctrine is expected to come from the inherited parent seed,
  7. score solution via `utils/reward.py`, grounding correctness against the private stored row and validating reported ids,
  8. after all child rollouts for the task finish, persist each successful rollout's separate `next_seed/` directory as a parent seed candidate for the next task,
  9. append run metadata to a growing JSONL log and print one-line summary per rollout.
- Lineage behavior:
  - the first task can bootstrap without a parent seed;
  - after bootstrap, missing parent seeds are terminal and the loop will not silently continue as a fresh lineage.
- Resume behavior:
  - runs automatically resume from existing `--runs-log` entries that match dataset/split/model/seed/generation/config/rollout-count;
  - completed rollouts are skipped, partial tasks continue from missing rollout indices;
  - parent lineage candidates are reconstructed from successful completed run records when possible, with `--rollout-temp-root/latest_parent_pool.json` kept as a fallback/cache;
  - disable this with `--no-resume`.
- Manual iteration:
  - use `--step` to run exactly one task iteration, choosing the first incomplete task from the resume log or the next new task;
  - use `--all-tasks --start-task-index N --max-tasks 1` to run a specific shuffled dataset task index.

# metalanguage

Open ended RSI

## Setup

Run the setup script from the repository root:

```bash
./setup.sh
```

The script installs `uv` if needed, uses `uv` to ensure Python 3.12 is
available, creates `.venv`, installs the SuperGPQA rollout runtime
dependencies, and verifies that `main_loop.py` imports correctly.

Useful variants:

```bash
./setup.sh --verify-only
./setup.sh --with-legacy-reward
```

Set the OpenRouter key in a local `.env` file:

```bash
OPENROUTER_API_KEY=your-key-here
```

The runner loads `.env` from the repository root. Real environment variables
take precedence over values in `.env`.

## Utilities

- `utils/reward.py`: reward/evaluation helpers used by training workflows.
- `utils/openrouter.py`: helpers for OpenRouter Responses API calls.
- `utils/task_store.py`: task-store persistence/redaction and rollout answer artifact helpers.
- `utils/budget_ledger.py`: file-backed token-budget ledger and seed budget metadata helpers.
- `utils/hf_datasets.py`:
  - `download_hf_dataset_to_file(...)` writes a Hugging Face dataset split to JSONL.
  - `HFDatasetDataLoader(...)` pulls dataset rows and yields mini-batches for training loops.

## Episode runner

- `main_loop.py`: runs RLVR-style episodes end-to-end:
  1. by default, sample one task from `m-a-p/SuperGPQA` (or process all tasks with `--all-tasks`; override with `--dataset-name`),
  1.5. use `moonshotai/kimi-k2.6` as the default OpenRouter model (override with `--model`),
  2. run 8 `--num-rollouts` child rollouts per task by default, concurrently in isolated temp workspaces (each with an auto-assigned unique rollout username),
  3. sample each child's parent (with replacement) from the prior task's successful rollouts,
  3.5. expose a shared cross-rollout workspace at `--rollout-temp-root/shared_workspace` where any rollout agent can leave files/messages for any other rollout agent (files written during the task batch are cleaned up after the batch; durable consequences must be copied into a seed, archive artifact, solution, or later behavior),
  3.6. assign every rollout instance a UUID and record an `instance_created` event in the token-budget ledger,
  4. expose `archive/world_repo` by default as the durable cross-lineage Git archive available to every rollout (override with `--archive-repo-dir`),
     using a per-rollout temporary worktree so only committed archive changes are merged back and uncommitted archive edits are discarded,
  5. copy the selected parent seed workspace into the child workspace, then write the current task as `task.md` with solution-like fields redacted,
  6. run OpenRouter worker with `run_bash` tool access and the minimal fixed prompt `Read README.md.`; operating doctrine is expected to come from the inherited parent seed,
     or run Codex with a fixed base-instructions pointer to the same inherited seed,
  7. score solution via `utils/reward.py`, grounding correctness against the private stored row and validating reported ids,
  8. after all child rollouts for the task finish, persist each successful rollout's separate `next_seed/` directory as a parent seed candidate for the next task only when `next_seed/README.md` exists and is non-empty,
  9. append run metadata to a growing JSONL log and print one-line summary per rollout.
- Runtime containment:
  - generated state is rooted at `~/Documents/metalanguage_runs` by default;
  - `--runs-log`, `--outputs-dir`, `--fixed-temp-dir`, `--rollout-temp-root`, `--task-store-dir`, `--archive-repo-dir`, and `--bootstrap-seed-dir` are resolved under `--runtime-root` when relative;
  - absolute overrides for those paths are rejected unless they stay inside `--runtime-root`;
  - `--runtime-root` itself is rejected unless it stays inside `~/Documents`;
  - Hugging Face caches, process temp files, and worker shell home/cache/temp defaults are also redirected under the runtime root.
- Budget ledger:
  - append-only ledger events are written to `logs/budget_ledger.jsonl` under the runtime root;
  - every rollout receives an internal `instance_uuid` recorded in progress logs, run logs, and the ledger;
  - budget allocation, solve rewards, and direct inter-instance transfers are intentionally left for future parent tool-call mechanics.
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

### Codex rollout backend

The default rollout backend remains OpenRouter. To run rollouts through the
Metalanguage-owned Codex runner, build the Rust runner once:

```bash
cargo build --manifest-path crates/metalanguage-codex-runner/Cargo.toml
```

Then run one Codex-backed rollout:

```bash
uv run python -B main_loop.py \
  --worker-backend codex \
  --model gpt-5.5 \
  --step \
  --num-rollouts 1
```

Useful flags:

- `--codex-build-runner`: build the runner before starting the episode.
- `--codex-runner-bin PATH`: use an explicit prebuilt runner binary.
- `--codex-home PATH`: choose the Codex auth/config directory.
- `--codex-sandbox-mode read-only|workspace-write|danger-full-access`: choose the
  rollout sandbox mode.
- `--codex-base-instructions-mode read-readme|codex`: choose whether Codex uses
  the fixed scaffold base instruction `Read README.md.` (`read-readme`, the
  default) or its model-catalog base instructions (`codex`).
- `--codex-initial-prompt TEXT`: choose the first user message. With
  `--codex-base-instructions-mode read-readme`, a useful value is
  `"Read runtime.md, then task.md."` so the seed README is not duplicated in the
  user turn.

Example with the seed README as the evolvable prompt and Codex base instructions
kept to the fixed scaffold pointer:

```bash
uv run python -B main_loop.py \
  --worker-backend codex \
  --model gpt-5.5 \
  --codex-base-instructions-mode read-readme \
  --codex-initial-prompt "Read runtime.md, then task.md." \
  --step \
  --num-rollouts 1
```

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
  2. run 8 bootstrap rollout slots by default with `--num-rollouts`, then let later task width be set by spawned child slots,
  3. assign each rollout index to the matching `spawn_child` slot claimed by the prior task's rollouts,
  3.5. expose a shared cross-rollout workspace at `--rollout-temp-root/shared_workspace` where any rollout agent can leave files/messages for any other rollout agent (files written during the task batch are cleaned up after the batch; durable consequences must be copied into a seed, archive artifact, solution, or later behavior),
  3.6. assign every rollout instance a UUID and record an `instance_created` event in the token-budget ledger,
  4. expose `archive/world_repo` by default as the durable cross-lineage Git archive available to every rollout (override with `--archive-repo-dir`),
     using a per-rollout temporary worktree so only committed archive changes are merged back and uncommitted archive edits are discarded,
  5. copy the selected parent seed workspace into the rollout workspace, then write the current task as `task.md` with solution-like fields redacted,
  6. run OpenRouter worker with `run_bash` tool access and the minimal fixed prompt `Read README.md.`; operating doctrine is expected to come from the inherited parent seed,
     or run Codex with a fixed base-instructions pointer to the same inherited seed,
  7. score answers submitted through `submit_solution(answer, task_id?, problem_uid?)`, grounding correctness against the private stored row and validating reported ids,
  8. after all rollouts for the task finish, advance lineage through the `spawn_child(seed_dir, initial_budget_tokens)` slots claimed by those rollouts,
  9. append run metadata to a growing JSONL log and print one-line summary per rollout.
- Runtime containment:
  - generated state is rooted at `~/Documents/metalanguage_runs` by default;
  - `--runs-log`, `--outputs-dir`, `--fixed-temp-dir`, `--rollout-temp-root`, `--task-store-dir`, `--archive-repo-dir`, and `--bootstrap-seed-dir` are resolved under `--runtime-root` when relative;
  - absolute overrides for those paths are rejected unless they stay inside `--runtime-root`;
  - `--runtime-root` itself is rejected unless it stays inside `~/Documents`;
  - Codex runner request, event, stderr, and continuation-context control files are written under `logs/rollout_control/<instance_uuid>/`, outside rollout and shared workspaces;
  - worker home/cache/temp state is written under `logs/rollout_state/<instance_uuid>/`, outside rollout and shared workspaces;
  - shared workspace write attribution is recorded only in the durable runtime log, not as supervisor-written files inside the shared workspace;
  - rollout-created or modified shared workspace files are deleted after the active rollout batch finishes;
  - Hugging Face caches and process temp files are also redirected under the runtime root.
- Budget ledger:
  - append-only ledger events are written to `logs/budget_ledger.jsonl` under the runtime root;
  - a rebuildable projection cache is written next to the ledger and is used for live `budget_status`, transfer, and spawn budget checks;
  - every rollout receives an internal `instance_uuid` recorded in progress logs, run logs, and the ledger;
  - provider-reported model usage is recorded as `token_usage` events after OpenRouter calls and Codex usage events;
  - `submit_solution(answer, task_id?, problem_uid?)` scores immediately, returns `correct`, `reward`, credited tokens, and updated budget status, and records `solution_scored` events;
  - correct `submit_solution` calls append one `solve_reward_credit` budget event per rollout, defaulting to 300000 tokens via `--solve-reward-token-credit-tokens`;
  - there is no answer-file scoring fallback; a rollout that does not call `submit_solution` receives no solution score or solve reward credit;
  - `--rollout-token-budget-tokens` sets each initial rollout's starting budget, defaulting to 300000 tokens, and stops a rollout when reported usage exhausts it;
  - rollouts can call `submit_solution(answer, task_id?, problem_uid?)`, `budget_status()`, `transfer_tokens(target_instance_uuid, amount_tokens)`, and `spawn_child(seed_dir, initial_budget_tokens)` as main-loop tools;
  - `transfer_tokens` moves budget from one live same-task rollout to another by instance UUID; the sender's remaining budget decreases and the target's effective budget increases;
  - `spawn_child` copies a complete workspace-local seed directory into the next claimed next-iteration rollout slot;
  - the claimed slot receives exactly `initial_budget_tokens`; the call fails if the parent rollout does not have that much budget remaining;
  - tool responses are counted when they are sent back as model input on the next model call.
- Lineage behavior:
  - the first task can bootstrap without a parent seed;
  - a rollout continues only by successfully calling `spawn_child(seed_dir, initial_budget_tokens)`;
  - solving/submitting alone does not continue lineage; if no rollout claims a child slot, that lineage dies and the loop exits with an error;
  - correct solves can add reward budget for spawning, while unsolved rollouts may still spawn with their lower remaining budget;
  - after bootstrap, missing parent seeds are terminal and the loop will not silently continue as a fresh lineage.
- Resume behavior:
  - runs automatically resume from existing `--runs-log` entries that match dataset/split/model/seed/generation/config/rollout-count;
  - completed rollouts are skipped, partial tasks continue from missing rollout indices using each task's recorded rollout count;
  - parent lineage candidates are loaded from `--rollout-temp-root/latest_parent_pool.json`, which is written from claimed `spawn_child` slots;
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

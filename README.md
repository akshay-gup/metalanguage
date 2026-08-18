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
- `utils/benchmark_events.py`: append-only benchmark submission, provenance, and official command events.
- `utils/hf_datasets.py`:
  - `download_hf_dataset_to_file(...)` writes a Hugging Face dataset split to JSONL.
  - `HFDatasetDataLoader(...)` pulls dataset rows and yields mini-batches for training loops.

## Episode runner

- `main_loop.py`: runs RLVR-style episodes end-to-end:
  1. by default, treat hard rows from the shuffled `m-a-p/SuperGPQA` split as the problem pool (override with `--dataset-name` and `--difficulty-filter`) and keep solved/cursor state in `--problem-queue`,
  1.5. use `moonshotai/kimi-k2.6` as the default OpenRouter model (override with `--model`),
  2. run a configured population of 8 rollouts by default with `--num-rollouts`, using bootstrap rollouts for positions without spawned parents,
  3. reserve one deterministic next-iteration child opportunity for each source rollout, keyed by `source_rollout_index` and the same `slot_index`,
  3.5. expose a shared cross-rollout workspace at `--rollout-temp-root/shared_workspace` where any rollout agent can leave files/messages for any other rollout agent (files written during the task batch are cleaned up after the batch; durable state can persist through a child workspace, committed archive artifact, solution, or later behavior),
  3.6. assign every rollout instance a UUID for provenance and isolated runtime state,
  4. expose `archive/world_repo` by default as the durable cross-lineage Git archive available to every rollout (override with `--archive-repo-dir`),
     using a per-rollout temporary worktree so only committed archive changes are merged back and uncommitted archive edits are discarded,
  5. inject the selected parent slot's stored prompt as the rollout's initial user text, copy that slot's inherited workspace directory into the rollout root and consume the slot workspace, and write `shared_workspace/BENCHMARK.md` plus `problem_pool.json` and `problem_pool.md`; bootstrap rollouts receive root `README.md` as a neutral environment description and a short initial message stating that no task is assigned,
  6. register main-loop tools through the worker backend (OpenRouter tool payloads or Codex `DynamicToolSpec` entries), then run the worker with the inherited prompt and generated runtime context; operating doctrine is expected to come from the inherited prompt,
     while `runtime.md` contains only generated paths, runtime IDs, the rollout's reserved child-slot index, and peer lists,
  7. score answers submitted through `submit_solution(uuid, answer)`, grounding correctness against the private stored row selected by uuid,
  8. let each rollout spawn at most one child with `spawn_child(prompt, workspace_dir)`; failed validation or copying can be corrected and retried, and spawning returns feedback without stopping the parent rollout or batch,
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
- Benchmark events and child slots:
  - append-only scoring, selection, and official command events are written to `logs/benchmark_events.jsonl` under the runtime root;
  - every rollout receives an internal `instance_uuid` recorded in progress logs, run logs, and benchmark events;
  - `submit_solution(uuid, answer)` scores immediately, returns `correct` and `reward`, and records `solution_scored` events;
  - there is no answer-file scoring fallback; a rollout that does not call `submit_solution` receives no solution score;
  - rollouts can call `submit_solution(uuid, answer)` and `spawn_child(prompt, workspace_dir)` as applicable main-loop tools;
  - `spawn_child` stores the required non-empty `prompt` in supervisor-side slot metadata as the child rollout's next initial user text;
  - `workspace_dir` is required and must be a workspace-local directory whose root contains a regular, non-symlinked, readable, non-blank UTF-8 `README.md`; `spawn_child` copies its contents into the reserved slot's inherited workspace, while additional files remain optional;
  - `workspace_dir` must be inside the rollout workspace and must not be the rollout root; after a successful spawn, the source directory is deleted when that parent rollout finishes, while failed attempts do not consume it;
  - root `README.md` is not copied implicitly;
  - `spawn_child` does not require or create `prompt.md`; prompt text lives in slot metadata/logs outside the child workspace;
  - each source rollout owns exactly one child opportunity at its `source_rollout_index`; the filesystem lock only makes concurrent state checks and recording atomic;
  - copying and copied-README revalidation happen before the child is recorded, so validation/copy failures remain retryable;
  - a successful call explicitly reports that the child was spawned and the parent continues; later calls from only that source rollout return structured `child_already_spawned` feedback and do not affect peers.
- Lineage behavior:
  - the first rollout batch can bootstrap without a parent slot;
  - a rollout's lineage gains an inherited child only through a successful `spawn_child(prompt, workspace_dir)` call; the source rollout itself continues normally after the tool result;
  - every spawned child has a stored initial prompt and an inherited workspace rooted by `README.md`;
  - the child README is expected to preserve the parent environment description's themes, while its exact wording and elaboration may evolve;
  - solving/submitting alone does not continue that rollout's lineage; after each iteration, every configured population position not filled by a successfully spawned child is a fresh bootstrap rollout using the base README and initial prompt;
  - there is no correctness gate for spawning; solved and unsolved rollouts may use their reserved child opportunity;
  - successfully spawned children form the next parent pool first; only the remaining configured population positions are reinitialized from the bootstrap seed.
- Resume behavior:
  - runs automatically resume from existing `--runs-log` entries that match dataset/split/model/seed/generation/config/rollout-count;
  - completed rollouts are skipped, partial tasks continue from missing rollout indices using each task's recorded rollout count;
  - `--problem-queue` is pool state, not the workspace copy: each task batch materializes all currently unsolved redacted problems in the shared workspace, and solved UIDs are marked only after the batch finishes so duplicate same-iteration solves can still receive reward;
  - parent lineage candidates are loaded from `--rollout-temp-root/latest_parent_pool.json`, which contains successful `spawn_child` records followed by fresh bootstrap entries for every remaining configured population position; inherited workspace directories are consumed when copied into a child rollout root;
  - disable this with `--no-resume`.
- Manual iteration:
  - use `--step` to run exactly one rollout batch, choosing the first incomplete batch from the resume log or the next pool batch index;
  - use `--all-tasks --start-task-index N --max-tasks 1` to run one rollout batch with pool scanning starting at shuffled dataset index `N`.
- Problem pool state:
  - `--problem-queue` stores persistent pool metadata, cursor, and solved problem IDs, and defaults to `logs/problem_queue.json` under `--runtime-root`;
  - `--difficulty-filter` selects which dataset difficulty values can enter the pool, defaulting to `hard`; pass `--difficulty-filter all` to include every difficulty or a comma-separated list such as `easy,middle`;
  - all currently unsolved redacted problems are written to `shared_workspace/problem_pool.json` and `shared_workspace/problem_pool.md`;
  - rollouts select a uuid directly from those shared pool files; there is no problem request or lease tool;
  - answers are scored only when the submitted uuid exists in that iteration's shared pool copy;
  - each uuid appears at most once in a generated pool copy, unsolved problems may reappear later with the same uuid, and after each rollout batch any problem solved by at least one rollout is removed from future pool copies.

### Codex rollout backend

The default rollout backend remains OpenRouter. To run rollouts through the
Metalanguage-owned Codex runner, build the Rust runner once:

```bash
cargo build --manifest-path crates/metalanguage-codex-runner/Cargo.toml
```

Then run one Codex-backed task iteration with 8 bootstrap rollout slots:

```bash
uv run python -B main_loop.py \
  --worker-backend codex \
  --model gpt-5.5 \
  --step \
  --num-rollouts 8
```

Useful flags:

- `--codex-build-runner`: build the runner before starting the episode.
- `--codex-runner-bin PATH`: use an explicit prebuilt runner binary.
- `--codex-home PATH`: choose the Codex auth/config directory.
- `--codex-sandbox-mode read-only|workspace-write|danger-full-access`: choose the
  rollout sandbox mode.
- `--codex-base-instructions-mode read-readme|codex`: choose whether Codex uses
  the fixed inherited-packet scaffold instruction (`read-readme`, the default)
  or its model-catalog base instructions (`codex`).
- `--codex-initial-prompt TEXT`: choose the first user message.

Example with Codex base instructions kept to the fixed inherited-packet
scaffold pointer:

```bash
uv run python -B main_loop.py \
  --worker-backend codex \
  --model gpt-5.5 \
  --codex-base-instructions-mode read-readme \
  --step \
  --num-rollouts 8
```

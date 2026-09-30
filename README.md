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

`main_loop.py` runs RLVR-style episodes: by default it draws hard rows from
the `m-a-p/SuperGPQA` split as the problem pool and runs a population of 8
rollouts (`--num-rollouts`). Each rollout works its task, can score answers
with `submit_solution`, and may spawn at most one child for the next iteration
(`spawn_child`), forming lineages; positions without a spawned child become
fresh bootstrap rollouts. Durable cross-lineage state lives in the
`archive/world_repo` Git archive, and a shared workspace is visible to every
rollout in a batch.

Generated state roots at `~/Documents/metalanguage_runs` (`--runtime-root`).
Runs resume from `--runs-log` (`--no-resume` disables); `--step` runs exactly
one rollout batch. Full behavioral spec: `docs/episode-runner.md`.

### Open-ended task profile

Use `--benchmark open-ended` to run infrastructure around one arbitrary
human-authored Markdown task without configuring a benchmark evaluator. A new
runtime requires `--task-file`:

```bash
uv run python -B main_loop.py \
  --benchmark open-ended \
  --task-file ./my-task.md \
  --runtime-root ~/Documents/metalanguage_open_ended \
  --step
```

- The task file's exact bytes are copied to
  `shared_workspace/BENCHMARK.md` at batch setup; no generated task text or
  placeholder is added.
- The runtime stores the exact content and its SHA-256 identity under
  `logs/open_ended_task/`. Later steps may omit `--task-file` and use that
  runtime-owned copy. If `--task-file` is supplied again, its bytes must match
  the recorded task.
- This profile creates no problem pool or catalog, private answer store,
  benchmark MCP server, benchmark-specific model tool, submission interface,
  solved-item state, evaluator, score, reward, solved/failed/no-attempt label,
  or ranking. Generic rollout tools, child spawning, shared workspace,
  artifacts, and archive behavior are unchanged.
- Run records and one-line summaries say `evaluation=unconfigured`. Worker
  status, artifacts, archive activity, and child spawns remain lifecycle
  diagnostics and are not treated as proxy scores.
- `--problem-pool-size` is rejected for this profile. A runtime claimed by one
  benchmark/profile cannot be reused for another.

### ARC-AGI-3 benchmark semantics

- ARC uses the same compatibility filenames, `shared_workspace/problem_pool.json`
  and `problem_pool.md`, as a reusable public environment catalog. Every official
  environment record remains eligible on every iteration, subject only to the
  optional deterministic `--problem-pool-size` sampling cap; a prior `WIN` never
  retires an environment.
- The overall human task is improving general ARC-AGI-3 capability for eventual
  hidden evaluation. A selected environment's official `WIN` and level progress
  remain rollout diagnostics and do not complete that overall objective.
- Rollouts interact only through the official `RESET` and `ACTION1`–`ACTION7`
  interface documented in `shared_workspace/BENCHMARK.md`.
- The driver reads the official Relative Human Action Efficiency score from
  `GET /api/scorecard/{card_id}`. `BenchmarkOutcome.reward` is that RHAE
  percentage in the explicit `official_rhae_percent_0_to_100` unit, not a 0–1
  fraction or binary WIN reward. It is `null` when the official score is
  unavailable, with an explicit outcome error; the game-specific endpoint's raw
  action/accounting metrics are retained separately.
- Batch means are labeled public-practice rollout RHAE aggregates because
  self-selected and repeated public environments are neither the official
  hidden score nor an official full-suite score. The official full-suite
  methodology averages environment scores, while each completed level uses the
  squared human-baseline/AI-action ratio, capped at 115%, 1-indexed level
  weighting, and a completion cap.
- `logs/arc_agi/benchmark_state.json` remains compatible with existing runtimes:
  its historical `solved_items` field is retained as an observed-environment-WIN
  ledger, but it has no effect on catalog eligibility.

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

The runner and CodeMode host are validated as one local build. The manifest
records the vendored Codex commit plus content fingerprints for its tracked and
nonignored source files, the runner crate, build helpers, and local Cargo config.
Dirty edits, additions, and deletions invalidate it even if modification times
are preserved. Ignored build products and the configured target directory are
excluded from source hashing. Executable file identities bind both binaries to
that build without hashing build outputs; copying or replacing either may require
a rebuild. Old binaries without a manifest fail closed with rebuild instructions.

Useful flags:

- `--codex-build-runner`: build the runner and matching CodeMode host before
  starting the episode. A successful paired build writes a local `.bundle.json`
  manifest beside the runner. Builds invalidate the old manifest and remove the
  two previous executable outputs first, so Cargo must produce both again, and
  reject source changes detected between their initial and final fingerprints.
- `--codex-runner-bin PATH`: use an explicit prebuilt runner binary with its
  adjacent host and valid build manifest; explicit paths do not bypass freshness
  validation. To build at another location, set `CARGO_TARGET_DIR` and retain the
  resulting `debug/` or `release/` bundle directory layout.
- `--codex-home PATH`: choose the Codex auth/config directory.
- `--codex-sandbox-mode read-only|workspace-write|danger-full-access`: choose the
  rollout sandbox mode.
- `--codex-base-instructions-mode minimal`: Codex receives `.` instead of its
  model-catalog instructions. Native project-document loading is disabled; a
  shared loader validates, injects, and atomically marks the actual rollout-root
  `AGENTS.md` while constructing the first backend request. The exact logical
  user prompt remains `Begin.` in that same request: Codex uses developer
  instructions, direct OpenRouter uses a developer input item, and OpenCode
  uses its prompt-level system field. This applies equally to fresh bootstrap,
  inherited-child, and bootstrap-reinitialized workspaces.

- `--codex-initial-prompt TEXT`: choose the first user message.

Directory-guidance injection internals (guide format, pre-tool gate, parser
bounds, message projection): `docs/directory-guidance-decay.md`.

#### Opt-in directory guidance decay (managed Codex and patched OpenCode)

The default remains cumulative. A **fresh runtime root** can opt in with
`--directory-agents-mode decay --directory-agents-decay-steps K`, where `K` is
an explicitly supplied positive integer (there is no default lifetime).
The versioned `directory_agents_policy.json` identity locks mode and K for
later iterations of that runtime. Cumulative runtimes cannot be
migrated in place; OpenRouter rejects decay. Codex and OpenCode may share a
decay runtime only when each slot meets its own managed runtime requirement.
Its custom CLI capability contract is `metalanguage-inference-v2`.
Stock OpenCode binaries do not satisfy its separate capability check; the
patch targets the vendored 1.18.21 tree.
A vendored Codex commit changes the bundle's source identity even
when source bytes stay equivalent; rebuild the paired runner/CodeMode host
when the freshness check requires it.

Root guidance stays fixed. A nested guide activated after acknowledged model
step `s` is visible for steps `s+1` through `s+K`, unless an observed access
renews it; expiry takes effect at request boundaries. Full internals:
`docs/directory-guidance-decay.md`.

Example using the minimal base placeholder and automatic root `AGENTS.md` loading:

```bash
uv run python -B main_loop.py \
  --worker-backend codex \
  --model gpt-5.5 \
  --codex-base-instructions-mode minimal \
  --step \
  --num-rollouts 8
```

### Mixed rollout configuration

Use repeated `--rollout-slot BACKEND=MODEL` flags for a fixed ordered mixed
Codex and OpenCode population. Use `--rollout-config PATH` for a strict
versioned pool that is shuffled without replacement across incoming lineage
slots at every task index. The config file's rollout count is inferred unless
an explicit `--num-rollouts` is also supplied, in which case the counts must
match. Resolved pool content, not the config path, forms the runtime identity;
each realized task assignment is persisted under `logs/rollout_assignments/`
before workers launch and is reused when that task is resumed.

For the checked-in six-model flash population:

```bash
uv run python -B main_loop.py \
  --rollout-config configs/rollouts/gpt6-astra-openrouter-flash.json \
  --step
```

### OpenCode rollout backend

The OpenCode backend uses a native TypeScript worker under Bun and one private
loopback OpenCode server/session per rollout. It consumes the pinned OpenCode
generated TypeScript contracts directly and does not require a separate build.

Models must use OpenCode's explicit `provider/model` form:

```bash
uv run python -B main_loop.py \
  --worker-backend opencode \
  --model provider/model \
  --step \
  --num-rollouts 8
```

Each rollout receives private HOME, XDG config/data/state/cache, SQLite, and
temporary roots. The TypeScript worker connects through OpenCode's authenticated
HTTP/SSE server boundary, validates source-audited CLI versions, injects exact
system instructions through a private config-scoped hook, translates benchmark
MCP servers and enforces tool allowlists with session permission rules,
redacts sensitive MCP payloads, and removes the private OpenCode state after
normalizing the result. `spawn_child` is an isolated config-scoped tool that
synchronously calls the existing Python supervisor; its result returns to the
same parent turn.

Useful flags include `--opencode-bin`, `--opencode-bun-bin`,
`--opencode-worker-script`, `--opencode-auth-file`, `--opencode-agent`,
`--opencode-variant`, `--opencode-allowed-versions`,
`--opencode-allowed-bun-versions`, `--opencode-provider-env`, and
`--opencode-base-instructions-mode read-readme|opencode`. Provider environment
credentials are selected from a reviewed provider-specific allowlist; additional
names must be explicit. Unrelated host environment variables are not inherited.

Custom-provider configuration and the full sandbox/security reference:
`docs/opencode-backend.md`.

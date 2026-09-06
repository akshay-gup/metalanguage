# metalanguage

Open ended RSI

## Historical v1 execution contract

The Codex/open-ended compatibility path is restored from outer source commit
`43ec789` (the last material v1 source used through historical task index 9).
It uses the bootstrap `seeds/bootstrap/README.md`, the
71-byte `read-readme` base instruction, independent linked Git worktrees and
`rollout/...` branches, copied child workspaces, and serial supervisor merges.
Uncommitted archive edits are discarded; conflicting branches are retained but
not merged. There is no peer-message bus, automatic delivery turn, polling
protocol, broadcast, store, or cursor. Metalanguage v3.7 adds only the direct,
pull-based private inbox described below to Codex/open-ended research turns.

OpenCode remains an explicitly selected, separate backend. Its adapter,
protocol metadata, and containment do not alter the Codex request, workspace,
Git, prompt, completion, or cleanup path.

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
  3.5. expose a shared cross-rollout workspace at `--rollout-temp-root/shared_workspace` where rollouts can leave readable files for other rollouts (files written during the task batch are cleaned up after the batch; durable state can persist through a child workspace, committed archive artifact, solution, or later behavior); this filesystem visibility is the historical v1 behavior and is not a peer-messaging API,
  3.6. assign every rollout instance a UUID for provenance and isolated runtime state,
  3.7. for Codex or OpenCode open-ended research, create each live rollout's private batch-local `messages/` inbox before workers launch; other named rollouts can place direct messages there only through `send_message(recipient, message)`, and recipients read files with ordinary filesystem tools if desired,
  4. expose `archive/world_repo` by default as the durable cross-lineage Git archive available to every rollout (override with `--archive-repo-dir`),
     using a per-rollout temporary worktree so only committed archive changes are merged back and uncommitted archive edits are discarded,
  5. inject the selected parent slot's stored prompt as the rollout's initial user text, copy that slot's inherited workspace directory into the rollout root and consume the slot workspace, and write `shared_workspace/BENCHMARK.md`; evaluated benchmark profiles also write their pool/catalog files, while the open-ended profile writes only the exact human-authored task; bootstrap rollouts receive root `README.md` as a neutral environment description and a short initial message stating that no task is assigned,
  6. register main-loop tools through the worker backend (OpenRouter tool payloads or Codex `DynamicToolSpec` entries), then run the worker with the inherited prompt and generated runtime context; operating doctrine is expected to come from the inherited prompt,
     while `runtime.md` contains only generated paths, runtime IDs, the rollout's reserved child-slot index, peer lists, and, for the private-inbox profile, its own fixed human name and roster,
  7. for SuperGPQA, score answers submitted through `submit_solution(uuid, answer)`, grounding correctness against the private stored row selected by uuid; other profiles retain their own explicitly documented evaluation semantics,
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
  - rollouts can call `submit_solution(uuid, answer)` and `spawn_child(prompt, workspace_dir)` as applicable main-loop tools; Codex and OpenCode open-ended research rollouts can also call `send_message(recipient, message)`;
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
- On the Codex and OpenCode backends, each research rollout has one fixed human name by
  rollout index: Daniel, Noah, Elizabeth, George, Eva, Eleanor, Zoe, and
  Oliver. `send_message` accepts one other live name and a non-empty UTF-8
  message. It atomically creates a unique sequence-and-sender file in that
  recipient's private `messages/` inbox. Messages are never injected into
  context, and there is no read, broadcast, polling, or delivery-turn API. The
  supervisor imposes no message-size, per-sender, or per-batch message quota;
  model turns and the filesystem provide the natural bounds. Stable backend call
  IDs are idempotent; without one, a retry may create another file.
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

Useful flags:

- `--codex-build-runner`: build the runner before starting the episode.
- `--codex-runner-bin PATH`: use an explicit prebuilt runner binary.
- `--codex-home PATH`: choose the Codex auth/config directory.
- `--codex-sandbox-mode read-only|workspace-write|danger-full-access`: choose the
  rollout sandbox mode. `danger-full-access` is rejected for Codex/open-ended
  private-inbox turns because it cannot enforce inbox privacy.
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

For Codex and OpenCode open-ended research, a rollout can read its own inbox but
cannot write, overwrite, delete, enumerate, or read another rollout's inbox.
Codex uses exact read-deny rules. OpenCode mounts ordinary sibling workspaces
read-only while replacing each sibling `messages/` directory with an empty
read-only directory. Inbox contents are excluded from child workspaces and
episode outputs and are removed with the batch workspaces. ARC, SuperGPQA,
controls, OpenRouter, and other unsupported paths expose no messaging tool.

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
normalizing the result. `spawn_child` and, for open-ended rollouts,
`send_message` are isolated config-scoped tools that synchronously call the
existing Python supervisor; their results return to the same parent turn.

The default Linux launcher uses bubblewrap with a private PID namespace,
only the runtime binaries and fixed MCP socket proxy mounted read-only, explicit
writable rollout/archive/shared roots, a private `/tmp`, and parent-death
cleanup. Linux, readable procfs, PID namespaces, and a working bubblewrap launch
are preflight requirements and fail closed. The Python lineage callback runs
outside the rollout sandbox behind a random authenticated loopback endpoint;
its command, context, logs, sibling inboxes, and spawn-slot state are not
mounted into the OpenCode server. Ordinary sibling rollout workspaces are
read-only. Callback crashes, malformed replies, and
timeouts return structured retryable tool results over HTTP 200 so the same
parent can retry and continue. Benchmark modes fail closed if bubblewrap is disabled. Network remains
explicitly enabled because the private HTTP server
boundary and provider calls cannot currently operate in a separate network
namespace; `--opencode-network-mode none` therefore fails closed. The
`unsafe-none` is rejected because open-ended inbox privacy and evaluated
benchmark containment both require bubblewrap.

The audited OpenCode API reports MCP connection status but does not enumerate
MCP tool IDs. The runner validates required connectivity and fails closed on
empty/invalid allowlists; unlisted tools are denied at execution time. For an
evaluated benchmark, every stdio benchmark server runs as a worker-supervised
host process outside the model bubblewrap. OpenCode can reach it only through a
single-use, per-rollout, mode-0600 Unix-socket capability and a fixed read-only
stdio proxy. The socket exposes only the exact MCP protocol; no benchmark
context, task store, event log, ARC state root, host command, bearer credential,
or writable benchmark root is mounted in the model sandbox. SuperGPQA and ARC
retain their native MCP names, schemas, immediate scoring, timeouts, resources,
and image-attachment path.

Useful flags include `--opencode-bin`, `--opencode-bun-bin`,
`--opencode-worker-script`, `--opencode-auth-file`, `--opencode-agent`,
`--opencode-variant`, `--opencode-allowed-versions`,
`--opencode-allowed-bun-versions`, `--opencode-provider-env`, and
`--opencode-base-instructions-mode read-readme|opencode`. Provider environment
credentials are selected from a reviewed provider-specific allowlist; additional
names must be explicit. Unrelated host environment variables are not inherited.

The native worker supports a narrow form of the official OpenCode
[custom-provider configuration](https://opencode.ai/docs/providers/#custom-provider)
for generic OpenAI-compatible endpoints. The provider portion of `--model`
must equal `--opencode-custom-provider-id`. The audited package allowlist is
`@ai-sdk/openai-compatible` for `/v1/chat/completions` and `@ai-sdk/openai` for
`/v1/responses`. Both packages are bundled by pinned OpenCode `1.18.29`, so the
worker never installs provider packages at runtime; any other package fails
before launch.

A complete custom configuration requires provider ID, display name, package,
base URL, and an API-key environment-variable name. Optional headers use
repeatable `--opencode-custom-provider-header-env HEADER=ENV_VAR`; literal key
or header values are not accepted. Context and output limits are optional but
must be supplied together. Plain HTTP is accepted only for loopback endpoints;
non-loopback endpoints require HTTPS.

The private config emits the documented `provider.<id>.npm`, `name`, `models`,
`options.baseURL`, `options.apiKey: "{env:VAR}"`, `options.headers`, and
per-model `limit.context`/`limit.output` fields.

For example:

```bash
export MY_PROVIDER_API_KEY='replace-me'
export MY_PROVIDER_TENANT='replace-me'
python3 main_loop.py \
  --worker-backend opencode \
  --model local-ai/my-model \
  --opencode-custom-provider-id local-ai \
  --opencode-custom-provider-name 'Local AI' \
  --opencode-custom-provider-npm @ai-sdk/openai-compatible \
  --opencode-custom-provider-base-url http://127.0.0.1:8000/v1 \
  --opencode-custom-provider-api-key-env MY_PROVIDER_API_KEY \
  --opencode-custom-provider-header-env X-Tenant=MY_PROVIDER_TENANT \
  --opencode-custom-provider-context-limit 32768 \
  --opencode-custom-provider-output-limit 4096
```

Only environment-variable names and other nonsecret settings enter the private
disposable config and run metadata. Secret values travel through the existing
allowlisted environment/fingerprint pipeline; run records contain their
aggregate fingerprint, not their values. Model-controlled shell children still
receive those variables blanked, while benchmark MCP children retain the
separate host-bridge environment policy.

Known path-valued credentials and certificate settings, including
`GOOGLE_APPLICATION_CREDENTIALS`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, and
`REQUESTS_CA_BUNDLE`, are validated and rebound read-only at stable per-variable
paths without mounting their parent directories.
Credential-directory inspection rejects nested symlinks and non-regular
entries and is bounded to 4,096 files, 64 MiB, and depth 16 before hashing or
mounting.
An auth file is read-only and copied into each isolated process through
`OPENCODE_AUTH_CONTENT`. Resume compatibility fingerprints the OpenCode and Bun
binaries/versions, bubblewrap path/version/content, TypeScript worker and Python
adapter/orchestration sources, exact effective system/configured initial prompt
content, relevant provider/auth inputs, and all exposed worker/startup sandbox
settings. A partial resume recomputes inherited effective prompt identity from
the current parent-pool child prompt and rejects a missing or mismatched hash.
Only pinned OpenCode `1.18.29` is source-audited (official tag `v1.18.29`,
commit `16747470f976aca3d362ad730bcd3fe82ecc2c9a`).

Host-side MCP commands receive only a small fixed base environment plus that
server's explicitly configured environment. OpenCode server credentials, auth
content, and provider keys are never forwarded to the host MCP process.

Private config roots contain a dependency declaration, matching root lock entry,
and an empty `node_modules` directory for the pinned OpenCode plugin version.
OpenCode's source then skips its detached dependency installer; npm is also
forced offline, so rollout startup cannot download config/plugin dependencies.

Assistant final prose is intentionally preserved in durable `WorkerResult`
output. Generic redaction protects protocol failures and sensitive MCP events,
but cannot soundly guarantee that a model will not repeat a benchmark answer in
ordinary prose. Benchmark answer privacy must therefore rely on tool-specific
redaction and benchmark policy, not semantic guessing over assistant text.

Bubblewrap materially limits filesystem and process access, but network access
is still allowed and the rollout workspace plus explicit archive/shared roots
remain writable. For evaluated benchmarks, session policy removes native
`bash`/`shell` tools and denies external-directory access. The fixed OpenCode
plugin also overwrites selected provider credentials, auth content, and server
tokens with empty values in any native shell child environment; this protects
trusted open-ended shell use from ordinary inheritance.

The unavoidable limitation is that provider credentials must still exist in the
OpenCode server process so it can call the provider. A defect in the audited
OpenCode process or fixed plugin could therefore access them, and allowed
network access remains an exfiltration surface. This is the strongest current
OpenCode-only fail-closed benchmark policy, not a hostile-use or Codex-parity
claim. Credential-hostile OpenCode rollouts remain unsupported.

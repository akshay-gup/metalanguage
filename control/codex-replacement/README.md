# Codex-Replacement (CR-v2)

Codex-Replacement is the second in-tree stock-Codex control. It is derived from
`../codex-additive` and keeps the same eight-slot harness,
model, benchmark, prompts, permissions, authentication isolation, passive
compaction observer, natural-turn barrier, session-survival rule, shared Git
checkout, evidence redaction, and batch-final cleanup.

The instruction-delivery treatment remains replacement, while both active v2
controls pin the same high reasoning effort. No other harness behavior changes.
The source instruction
is `seed/model_instructions.md`, byte-for-byte equal to the aligned canonical
control text used by the additive control. Every private `CODEX_HOME` receives a
read-only copy named `model_instructions.md`, and its strict `config.toml` sets:

```toml
model_instructions_file = "model_instructions.md"
project_doc_max_bytes = 0
```

The shared 1,799-byte text preserves the canonical heading order except for the
removed successor heading, as well as its tone, paragraph order, work-until-room-
runs-out language, round language, shared Git cleanup, `BENCHMARK.md`, and
no-assignment neutrality. Its only deltas remove the full successor section for
unavailable `spawn_child` and the false spawn-input purpose from the
`seed_output/` line. The canonical
source and output are byte-pinned so extra drift fails closed.

The current official Codex config reference describes
`model_instructions_file` as a replacement for built-in instructions instead of
`AGENTS.md`; the pinned Codex source explicitly tests that a zero project-document
byte limit disables discovery. No `AGENTS.md` or `AGENTS.override.md` is created
in a rollout, project, or private `CODEX_HOME`, and the rollout permission map has
no project-instruction exception. Provider-free validation resolves and hashes
the configured private replacement file, checks the bundled base hash is
different, and confirms stock `debug prompt-input` contains exact `Begin.` but
zero additive copies of the rollout contract. Codex transports base instructions
in the separate request `instructions` field, which that debug command does not
render; the supported config semantics and pinned source tests establish the
replacement behavior without sending a request.

“Replacement instructions” does not mean literally zero system context. Stock
Codex and the provider retain unavoidable platform, tool-schema, protocol, and
user-message layers. This treatment replaces Codex's configurable built-in base
instructions and removes additive project-document delivery; it does not and
cannot remove those platform-level layers.

## Shared semantics

Each iteration selects exactly eight stock Codex sessions. Every selected
session receives one ordinary turn and may finish naturally. There is no `Stop`
hook, finalization block, same-turn continuation, forced compaction, retry, or
replacement within the current iteration. The only hook is a passive
`PostCompact` observer matching `auto`; it increments a durable counter and
returns no behavior directive.

After all eight turns exit successfully, counter deltas decide the next pool. A
slot with one or more automatic compactions retains that exact session ID for
one resume in the next explicitly launched iteration. A zero-delta slot becomes
fresh/null and receives a brand-new session with exact prompt `Begin.` next time.
Mixed survivor/fresh pools are supported. Any launch, process, stream, session,
turn-completion, integrity, or cleanup error leaves the batch incomplete without
retry or silent state advance.

All slots use one literal `runtime/shared_workspace/archive/` checkout: the same
worktree, index, `HEAD`, branch, refs, objects, and locks. It begins as an empty
repository with unborn `main`, no refs, objects, files, or remotes. There is no
supervisor merge/commit/branch choice. Concurrent sessions can see ordinary Git
lock, checkout, and content races. On successful finalization, cleanup preserves
commits, refs, `HEAD`, and branch while removing staged, modified, deleted,
untracked, ignored, and batch-local shared state.

The exact 173-byte external problem is outside Git and visible read-only only at
the common Metalanguage location `shared_workspace/BENCHMARK.md`; its presence
is optional and not an assignment, and no evaluator is configured.
Every rollout has a read-only `runtime.md`, a private writable `seed_output/`
emptied before each explicit iteration, and a private `CODEX_HOME`. The only
authentication reference is a symlink to the existing stock `auth.json`; auth
bytes are not copied and captured output is redacted. Network, web search, MCP,
apps, plugins, native multi-agent, spawning, browser/computer/image
features, goals, and memories are disabled or absent.

The exact stock project trust entry is preseeded and the complete config hash is
pinned. Trust enables the configured passive hook but grants no filesystem or
network access. Any config mutation, replacement-file mutation, hook drift,
additive instruction file, archive identity change, or other layout drift fails
closed.

## Layout and parity

```text
control/codex-replacement/
  control.py
  hooks/iteration_boundary.py       passive PostCompact observer only
  seed/model_instructions.md        pinned replacement base instructions
  seed/BENCHMARK.md                 exact 173-byte external problem
  seed/PINS.json                    identity, treatment, and parity pins
  tests/fake_codex.py
  tests/test_control.py
  runtime/                          ignored independent active state/evidence
    shared_workspace/archive/       one empty unborn Git repository
    shared_workspace/BENCHMARK.md   read-only external problem
    rollouts/rollout_000..007/
      runtime.md                    read-only slot/path facts
      seed_output/                  private writable output
    state/rollout_000..007/codex_home/
      config.toml
      model_instructions.md         read-only private replacement copy
```

`seed/PINS.json` records the source control pins and reviewed config differences.
The focused parity test compares parsed configs after normalizing only control
paths. It permits exactly three delivery differences: adding
`model_instructions_file`, changing `project_doc_max_bytes` from 32768 to 0, and
removing the rollout `AGENTS.md` read exception. It separately requires equality
of the archive seed, exact benchmark, canonical transformation, prompts, pinned CLI,
model, reasoning effort, slot count, and iteration semantics. The replacement
file must also remain the exact reviewed transformation of the current canonical
Metalanguage bootstrap at `../../seeds/bootstrap/README.md`.

## Provider-free setup and validation

Initialization hash-verifies the pinned stock launcher/native binary without
executing Codex and refuses to overwrite an existing runtime:

```bash
cd /home/akshay/Documents/metalanguage/control/codex-replacement
python3 control.py init --offline-pinned-codex
python3 control.py status
python3 control.py preflight
python3 -m unittest discover -s tests -v
python3 -m py_compile control.py hooks/iteration_boundary.py tests/fake_codex.py tests/test_control.py
```

`status`, tests, offline initialization, and `preflight` make no provider/model
call. Preflight rematerializes the exact pinned shared benchmark if normal batch-final
cleanup removed it, then uses local stock CLI inspection plus disposable Git and
sandbox fixtures. It verifies the exact configured replacement path/bytes/hash,
zero additive contract copies in prompt input, disabled AGENTS discovery,
benchmark/runtime readability and immutability, private output/shared Git writes,
forbidden-path denial, hook/tool controls, and config integrity.

These are the only commands that launch live model turns, and are intentionally
not part of setup or validation:

```bash
python3 control.py run-one-iteration
python3 control.py resume-next-iteration
```

The first is valid only for the initial eight null slots; the second runs one
later mixed pool. Codex-Additive, the separate standalone
control, Metalanguage runtime/archive, dependencies, submodules, and
`node_modules` are not used or modified by this control.

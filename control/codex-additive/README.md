# Codex-Additive (CA)

Codex-Additive is the in-tree comparison control that runs exactly eight slots
of the installed, unmodified stock Codex CLI. It is not a Metalanguage runtime:
it has no custom
worker, model-facing messaging, spawn operation, native multi-agent feature, or
supervisor that chooses branches, merges, or commits.

The model-visible additive `AGENTS.md` is the exact output of a reviewed,
fail-closed transformation of the current canonical Metalanguage bootstrap at
`seeds/bootstrap/README.md`. It preserves the canonical headings, order, tone,
and compatible paragraphs. The explicit deviations identify eight stock Codex
sessions/private rollouts, replace context exhaustion with one natural turn,
make later rounds explicit, remove unavailable messaging and spawning, change
`BENCHMARK.md` to optional `shared_workspace/TASK.md`, and describe passive
automatic-compaction survival. It also minimally qualifies the canonical
archive discard as occurring after a successful round, matching fail-closed
incomplete-batch behavior. Validation pins both the canonical source and
the transformed output; an unreviewed independent paraphrase is rejected.

Every iteration launches one ordinary turn for each slot and accepts its
natural final answer and process completion. The control never installs a
`Stop` hook, blocks finalization, injects a same-turn continuation, or forces
context compaction. Its only hook is a `PostCompact` matcher for `auto`; that
hook passively and durably increments the slot counter and returns no behavior
directive.

At successful batch finalization, each slot's counter before and after its turn
is compared. A slot with one or more observed automatic compactions retains the
exact session ID for the next iteration. A slot with no automatic compaction is
set to fresh/null. The next explicitly launched iteration resumes each retained
session once with the existing neutral continuation input and starts a new
stock Codex session for each null slot with the exact prompt `Begin.`. Fresh
replacements are never launched during the iteration that discarded their
predecessors.

An iteration completes only when all eight natural turns exit successfully.
Any launch, process, stream, session-identity, or turn-completion error marks it
incomplete without retry, cleanup, or next-slot advancement.

## Shared Git and private state

All slots see one literal `shared_workspace/archive/` checkout, including the
same worktree, index, `HEAD`, current branch, refs, and locks. It starts as a
genuinely empty repository with unborn `main`, no refs, objects, tracked files,
worktree files, or remotes. The exact task is hash-pinned outside Git and is
visible once at `shared_workspace/TASK.md`, read-only. There is deliberately no
second top-level `TASK.md` symlink: that redundant crossing conflicts with the
stock sandbox's read-only task mount.

Each slot has a private rollout directory and private `CODEX_HOME`. Only the
existing stock Codex `auth.json` is referenced by symlink; authentication bytes
are not copied, and captured stdout/stderr is redacted before being written.
Global user plugins, apps, MCP servers, skills, and session history are absent
from each freshly initialized private home. Native multi-agent features are
disabled, while private stock session history is retained only to support an
eligible slot's exact-session resume in a later iteration.

Each rollout also has a read-only `runtime.md` containing its exact slot roster
and relevant private/shared paths, plus a private writable `seed_output/` that
is emptied before every explicitly launched round. These are real minimal
equivalents of the canonical bootstrap references; neither adds a tool or
successor API.

Each generated private config pre-seeds the one exact stock project trust entry
for `/home/akshay/Documents/metalanguage`. Its path, value, and complete config
hash are pinned. This prevents stock Codex from appending the same entry at
startup; any other config mutation still fails closed. Project trust only
allows the configured passive hook to load and does not grant filesystem or
network access. No hook-trust bypass flag is used. The shared workspace is an
explicit narrowly writable filesystem path rather than a second stock workspace
root; its exact task path is a more-specific read-only exception. This avoids
synthetic top-level task mounts and conflicting shared project-document binds.

After all eight turns stop successfully, cleanup validates the canonical root
and `.git` identities, lock and operation state, then uses `git reset --hard
HEAD` for committed `HEAD` or `git read-tree --empty` for unborn `HEAD`, followed
by `git clean -ffdx`. It preserves committed objects, refs, `HEAD`, and the
current branch while discarding staged, uncommitted, untracked, ignored, and
batch-local shared state. Unknown or incomplete cleanup fails closed and does
not advance the next-slot pool. Recovery bundles are never active state.
Historical iteration manifests remain immutable control evidence; previously
deleted failed-run evidence remains absent.

## Layout

```text
control/codex-additive/
  control.py
  hooks/iteration_boundary.py   passive PostCompact observer only
  seed/AGENTS.md
  seed/TASK.md
  seed/PINS.json
  tests/fake_codex.py
  tests/test_control.py
  runtime/                      ignored active state/evidence
    shared_workspace/archive/   one empty shared Git repository
    shared_workspace/TASK.md    exact 173-byte read-only task
    rollouts/rollout_000..007/
      runtime.md                read-only exact roster/path facts
      seed_output/              private writable, empty at round start
    state/rollout_000..007/codex_home/
    iterations/
```

Initialization verifies the pinned launcher/native binary by hash without
executing Codex and refuses to overwrite an existing runtime:

```bash
cd /home/akshay/Documents/metalanguage/control/codex-additive
python3 control.py init --offline-pinned-codex
python3 control.py status
python3 control.py preflight
```

`status` and `preflight` do not make provider/model calls. Preflight uses local
stock CLI inspection and disposable Git/sandbox fixtures. It rematerializes the
exact pinned shared task if normal batch-final cleanup removed it, then proves
the single model-visible task and `runtime.md` are readable but not writable, the direct
top-level task is absent, private `seed_output/` and shared Git metadata are
writable, forbidden live paths remain unreadable, and all private config hashes
are unchanged after those stock CLI calls. The following two
commands do make provider/model calls and are intentionally not part of setup
or validation:

```bash
python3 control.py run-one-iteration
python3 control.py resume-next-iteration
```

`run-one-iteration` is valid only for the initial eight null slots.
`resume-next-iteration` is valid after a complete iteration and supports any
mixture of retained session IDs and fresh/null replacements.

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile control.py hooks/iteration_boundary.py tests/fake_codex.py tests/test_control.py
git diff --check
python3 control.py preflight
```

The fake CLI suite is provider-free and uses disposable repositories. It covers
natural completion with or without compaction, absence of `Stop`, passive
`PostCompact`, mixed resume/fresh selection, exact session identity, incomplete
failure behavior, shared inode identity, redaction, and cleanup for unborn and
committed repositories. A focused transformation test renders the control
instruction directly from the pinned canonical bootstrap and requires
byte-for-byte equality with `seed/AGENTS.md`, while separately pinning the small
reviewed deviation list.

The standalone reference at
`/home/akshay/Documents/codex_compaction_shared_git_control` is separate and is
never used or modified by this control.

The narrow in-repository compatibility symlink
`control/codex_compaction_shared_git_control -> codex-additive` keeps absolute
paths recorded by the first ten CA iterations usable. New commands, generated
metadata, and documentation use only the canonical `control/codex-additive`
path; historical iteration manifests are not rewritten.

# Metalanguage control: stock Codex automatic-compaction shared Git

This is an in-tree comparison control, not the Metalanguage runtime. It runs
exactly eight persistent sessions of the installed, unmodified stock Codex CLI
without using Metalanguage workers or orchestration. Each session has a private
rollout directory and private `CODEX_HOME`; all eight receive the same literal
shared workspace and the same `archive/` working tree, index, `HEAD`, current
branch, and refs.

The active archive starts as a genuinely empty Git repository: symbolic `HEAD`
targets an unborn `main`, there are no commits, refs, tracked files, stored Git
objects, worktree files, or remotes. `TASK.md` is hash-pinned outside the
repository in `shared_workspace/`.

The launcher has no semantic orchestration. It starts eight CLI processes,
records their evidence, waits for one automatic compaction per session, checks
the eight-way barrier, and performs the specified post-batch reset/clean. It
does not create archive worktrees, select branches, merge, commit, resolve
conflicts, or relaunch failed rollouts.

## Prepared layout

```text
metalanguage/control/codex_compaction_shared_git_control/
  control.py                 deterministic standard-library launcher
  hooks/iteration_boundary.py
  seed/AGENTS.md             additive neutral project instruction
  seed/TASK.md               exact hash-pinned runtime task bytes
  seed/PINS.json             reproducibility pins
  tests/fake_codex.py
  tests/test_control.py
  runtime/                   ignored, private runtime evidence
    shared_workspace/TASK.md exact task bytes, outside Git
    shared_workspace/archive one empty shared Git repository
    rollouts/rollout_000..007
    state/rollout_000..007/codex_home
    iterations/              JSONL, stderr, messages, manifests
```

`runtime/`, optional local recovery material, auth/session directories, and
evidence outputs are ignored by the surrounding Metalanguage repository.
Initialization uses `git init --initial-branch main` and verifies the empty
object database, empty index/ref set, unborn `HEAD`, empty worktree, ordinary
private `.git`, and absence of remotes or alternate/shared object storage.

The original standalone reference, including its preserved pre-correction RH
snapshot, remains at `/home/akshay/Documents/codex_compaction_shared_git_control`.
It is not copied into this repository and is never used by this control.

Authentication bytes are not copied: each private `CODEX_HOME` has only a
symlink to the existing stock Codex `auth.json`. Evidence is screened against
auth/environment secret values before it is written.

## Commands

These commands are local and deterministic except for the two iteration
commands, which make model/provider calls:

```bash
cd /home/akshay/Documents/metalanguage/control/codex_compaction_shared_git_control
python3 control.py init --offline-pinned-codex
python3 control.py status
python3 control.py preflight
python3 control.py run-one-iteration
python3 control.py resume-next-iteration
```

`run-one-iteration` is valid only for the initial eight fresh sessions and sends
the exact user input `Begin.`. `resume-next-iteration` is valid only after a
complete prior iteration and resumes the eight recorded session IDs with the
same neutral continuation input. If any rollout exits before its automatic
compaction, the manifest is marked incomplete, no rollout is relaunched, and no
post-batch cleanup runs.

`init --offline-pinned-codex` creates the ignored runtime without executing
Codex: it locates and hashes the pinned launcher/native binary, creates the
empty shared archive, and prepares eight zero-state rollout homes. A repeated
initialization refuses to overwrite an existing runtime.

## Boundary and cleanup

The stock `Stop` hook keeps a turn open until its target automatic compaction.
The `PostCompact` hook matches only `auto`, atomically increments the private
counter, and returns `continue: false`. A batch succeeds only when all eight
counters advance by exactly one.

After a successful barrier, cleanup first validates the canonical archive path,
root and `.git` inodes, absence of Git lock files, and a recognized operation
state. It quits recognized sequencer operations without moving refs. With a
committed `HEAD` it runs `git reset --hard HEAD`; with an unborn `HEAD` it uses
`git read-tree --empty`. It then runs `git clean -ffdx`, verifies that `HEAD`,
branch, and every ref are byte-identical to their pre-cleanup values, and
deletes every batch-local shared entry except `archive/`. Thus commits and refs
created by agents survive cleanup while dirty, ignored, staged, and untracked
state does not. Unknown states and incomplete cleanup fail closed.

## Stock context and permissions

Codex's own built-in model instructions remain in place. The neutral environment
is additive through `AGENTS.md`; `model_instructions_file` is not used. Global
user config, plugins, MCP servers, session history, and skills are absent because
each rollout uses a newly generated private `CODEX_HOME`; only authentication is
referenced. Stock built-in instructions and any administrator-managed
requirements remain authoritative because supported per-run configuration does
not replace or bypass them; `preflight` records the observed stock instruction
and rendered-prompt hashes. Apps/plugins, hosted browsing/search, goals, and
native multi-agent features are disabled with supported stock config.

The custom stock permission profile is narrower than full access: commands can
read minimal runtime paths and the pinned stock Codex installation, and write
only the private rollout plus the one shared workspace, with command network
disabled. It grants no model-command access to the surrounding Metalanguage
tree, live runtime, or stock auth file. A direct profile rule, rather than
legacy `workspace-write`, is necessary because stock legacy sandboxing protects
`.git` as read-only. `preflight` proves the permission boundary and Git-metadata
write behavior without mutating the prepared archive.

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile control.py hooks/iteration_boundary.py tests/fake_codex.py tests/test_control.py
git diff --check
```

The fake CLI tests exercise eight-way overlap, exact prompts and disabling
config, session capture/resume, hook behavior, counting, incomplete barriers,
shared inode identity, redaction, and cleanup across tracked, untracked,
ignored, nested-repository, unborn-HEAD, committed-HEAD, and interrupted-merge
state. They use only disposable temporary Git repositories.

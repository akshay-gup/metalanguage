# Rollout Environment

A rollout has a finite lifetime. The environment does not assign it an
objective. Human tasks, existing artifacts, peer activity, continuation,
creation, collaboration, and inactivity are all possible parts of the
environment.

## Workspace

- `README.md` is the stable bootstrap description of the environment.
- `runtime.md` contains generated facts for the current rollout, including
  paths, instance identity, peer instances, and the reserved child-slot index.
- `shared_workspace/` is visible to every rollout in the current batch.
- `archive/` is a shared Git worktree backed by the persistent world archive.
- `seed_output/` is local writable space within the rollout.
- Other inherited files, when present, came from a parent-provided child
  workspace.

Current runtime and tool results can differ from inherited artifacts because
inherited artifacts describe earlier states of the environment.

## Human Tasks

`shared_workspace/` contains the currently available human-task material:

- `BENCHMARK.md` describes the current benchmark interface and official
  completion policy;
- `problem_pool.md` and `problem_pool.json` contain the current working set.

Human tasks are optional opportunities rather than an assigned objective. Each
stable item identifier occurs at most once in a generated pool copy. Eligible
incomplete items can reappear later with the same identifier. Officially
completed items can leave later pools after batch finalization. Same-batch
rollouts can interact independently with the same item.

Official completion is recorded only through the benchmark-specific interface.
Shared conclusions and artifacts do not themselves count as official
completion.

## Shared And Durable State

Files in `shared_workspace/` are visible to same-batch peers. Rollout-created
files there are ephemeral and can be removed after the batch.

Committed changes in `archive/` can persist globally across batches. Uncommitted
archive changes are discarded when the rollout worktree is finalized.

A workspace-local directory passed through `spawn_child` is copied for that
rollout's possible child. A valid child workspace has a regular, non-symlinked,
readable, non-blank UTF-8 `README.md` at its root. Additional files are optional.
Generated runtime files, pool snapshots, transcripts, and other files are not
inherited unless they are included in the supplied workspace.

## Continuation

An individual lineage continues only through a successful call of:

```text
spawn_child(prompt="...", workspace_dir=...)
```

Each rollout has one reserved child opportunity and can successfully spawn at
most one child. Invalid or failed validation/copy attempts can be corrected and
retried. After success, later calls from that rollout return failure feedback
without affecting peers. Every call returns a tool result, and the parent
rollout continues normally. Spawning is independent of human-task attempts and
benchmark completion. A child receives the supplied prompt and a copy of the
supplied workspace-local directory.

After an iteration, population positions without a spawned child are
reinitialized from the base bootstrap environment. They do not inherit the
prompt or workspace of a rollout that did not spawn a child.

For a spawned child, the inherited `README.md` should thematically replicate
this environment description: finite lifetime, no assigned objective, optional
human tasks, shared and durable state, and child-slot mechanics. Exact wording
is not required; the description can be rewritten, extended, or evolved while
preserving those themes.

## Available Tools

- Benchmark-specific tools correspond to the current benchmark driver. Their
  interface is described in `shared_workspace/BENCHMARK.md`.
- `spawn_child(prompt, workspace_dir)` copies and validates the required
  workspace-local directory, then atomically records the child in this
  rollout's reserved next-iteration slot and stores its prompt. Invalid or
  failed attempts can be retried; after one successful spawn, further calls
  from this rollout fail while the parent continues.

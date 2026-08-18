# Rollout Environment

A rollout has a finite lifetime. The environment does not assign it an
objective. Human tasks, existing artifacts, peer activity, continuation,
creation, collaboration, and inactivity are all possible parts of the
environment.

## Workspace

- `README.md` is the stable bootstrap description of the environment.
- `runtime.md` contains generated facts for the current rollout, including
  paths, instance identity, peer instances, and child-slot capacity.
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

A workspace-local directory passed through `spawn_child` is copied into that
child slot. Generated runtime files, pool snapshots, transcripts, and other
files are not inherited unless they are deliberately included in such a
workspace.

## Continuation

An individual lineage continues only through a successful call of:

```text
spawn_child(prompt="...", workspace_dir=...)
```

Child slots are competitive and first-come first-served. A rollout can claim
multiple slots while capacity remains. Spawning is independent of human-task
attempts and benchmark completion. A child receives the supplied prompt and,
when present, a copy of the supplied workspace-local directory.

After an iteration, unclaimed population slots are reinitialized from the base
bootstrap environment. They do not inherit the prompt or workspace of a
rollout that did not claim them.

## Available Tools

- Benchmark-specific tools correspond to the current benchmark driver. Their
  interface is described in `shared_workspace/BENCHMARK.md`.
- `spawn_child(prompt, workspace_dir)` atomically claims a next-iteration child
  slot, stores its prompt, and optionally copies a workspace-local directory.
  It fails when no slot remains.

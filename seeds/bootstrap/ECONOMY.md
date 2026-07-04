# Economy

## Budget And Spawn

Budget is the rollout's spendable resource for the current task and future task
attempts. Use `budget_status()` to inspect configured budget, spent tokens,
transfers, reserved child budget, and remaining budget.

Lineage continues only through a successful
`spawn_child(prompt, initial_budget_tokens, workspace_dir)` call.
`submit_solution(uuid, answer)` can add reward budget on correct solves, but
submission by itself does not create a successor. An unsolved rollout can still
spawn only if it retains at least the minimum child budget. A child slot is only
useful if it receives enough budget to solve and spawn again; correct solves are
the main way to earn that budget. The minimum valid child budget is
`minimum_child_budget_tokens` from `runtime.md`, equal to the configured initial
rollout budget.

Treat continuation as part of task completion, not as a separate epilogue. Child
slotting is competitive: slots are first-come first-served, one rollout may
claim multiple child slots, and the batch can end once all child slots are
claimed. Each successful child slot becomes a later rollout assigned another
task. Preferred loop: solve one tractable problem, call `submit_solution`, use
the returned budget status or `budget_status()` to choose an
`initial_budget_tokens` value no larger than remaining budget, write a durable
successor prompt, and call `spawn_child`. `initial_budget_tokens` must also be
at least `minimum_child_budget_tokens`.

`spawn_child` stores the required non-empty `prompt` in supervisor-side slot
metadata as the child rollout's initial prompt. If `workspace_dir` is provided
and non-blank, it must name a workspace-local directory that is not the rollout
root; its contents are copied into the child slot's inherited workspace. The
same source directory can be reused for multiple child slots in the same parent
rollout and is deleted when that parent rollout finishes. If `workspace_dir` is
omitted or blank, the child gets no inherited workspace files beyond generated
runtime files, symlinks, and `seed_output/`. The child slot receives exactly
`initial_budget_tokens`; the call fails if that value is below
`minimum_child_budget_tokens`, if the parent does not have that much remaining
budget, or if the task's child slots are already full.

`transfer_tokens(target_instance_uuid, amount_tokens)` can move budget to a live
same-task peer listed in `runtime.md`.

## Successor Contract

Pass the successor prompt directly to `spawn_child(prompt=...)`. Do not create
or depend on `prompt.md`; prompt text belongs in slot metadata/logs, not in the
child workspace.

A valid minimal successor prompt is a compact continuation of the current core
instructions. It should preserve enough for the next rollout to:

1. read `runtime.md` and the shared problem pool;
2. solve one or more problems from `shared_workspace/problem_pool.md` or
   `shared_workspace/problem_pool.json`;
3. call `submit_solution(uuid, answer)`;
4. use `archive/` and `shared_workspace/` when useful;
5. call `spawn_child(prompt=..., initial_budget_tokens=..., workspace_dir=...)`
   again before stopping.

Optional inherited workspace files may be written under
`seed_output/workspace/` or another workspace-local directory, then passed as
`workspace_dir`. Use that only for files the next rollout should actually see in
its root workspace; the source directory is consumed when the parent rollout
finishes.

The successor prompt and optional workspace are durable successor content, not a
transcript. Revise them only when the change improves the durable setup, tool
contract, resource economy, or continuation mechanics.

Do not place generated runtime files, problem statements, snapshots,
orchestrator metadata, or hidden supervisor state into the successor prompt or
optional workspace.
Runtime paths, task content, instance IDs, budgets, peer lists, and slot metadata
belong to the harness/runtime layer.

## Archive

The archive Git repository path is in `runtime.md`. The archive is durable
cross-lineage memory for task solving. Use it only for compact artifacts that
should outlive the current rollout workspace and help later rollouts solve later
tasks.

Archive material should be selective, navigable, and intentionally committed.
Raw scratch work belongs in the rollout workspace, not the archive.

## Shared Workspace

The shared live workspace path is in `runtime.md`. It is an ephemeral same-task
workspace for concurrently active rollouts. Use it when useful for
communication with other workers: leave small notes, status updates, questions,
or coordination files that help the batch collaborate on the current task.

Shared workspace files are temporary. Durable consequences must be copied into a
successor prompt, optional child workspace, archive artifact, solution, or later
behavior before the active rollout batch ends.

Keep shared workspace notes small, flat, and easy to scan. Do not rely on the
shared workspace as durable memory.

## Evolution

The successor prompt is evolvable, not append-only. Successors may revise the
durable instructions when the change improves the setup, tool contract,
resource economy, or continuation mechanics.

Do not promote problem-specific context, generated runtime context, generated
task context, or one-rollout scratch material into durable successor content.

# Economy

## Budget And Spawn

Budget is the rollout's spendable resource for the current task and future task
attempts. Use `budget_status()` to inspect configured budget, spent tokens,
transfers, reserved child budget, and remaining budget.

Lineage continues only through a successful `spawn_child(seed_dir,
initial_budget_tokens)` call. `submit_solution(answer)` can add reward budget on
correct solves, but submission by itself does not create a successor. An
unsolved rollout can still spawn with its lower remaining budget.

Treat continuation as part of task completion, not as a separate epilogue. Each
successful child slot becomes a later rollout assigned another task. After
`submit_solution` returns, use the returned budget status or `budget_status()` to
choose an `initial_budget_tokens` value no larger than remaining budget, write a
successor seed, and call `spawn_child` before emitting a final message.

`spawn_child` copies a complete workspace-local seed directory into one claimed
next-iteration rollout slot. The child slot receives exactly
`initial_budget_tokens`; the call fails if the parent does not have that much
remaining budget.

`transfer_tokens(target_instance_uuid, amount_tokens)` can move budget to a live
same-task peer listed in `runtime.md`.

## Seed Contract

Write the successor seed under `seed_output/` before calling `spawn_child` with
`seed_dir` set to `seed_output`.

A valid minimal successor seed is a copy of the current durable packet files:
`README.md`, `SETUP.md`, and `ECONOMY.md`. Revise those files only when the
change improves the durable setup, tool contract, resource economy, or
continuation mechanics.

A successor seed is durable seed content, not a transcript. It should preserve
the packet shape and read order:

1. `README.md`
2. `SETUP.md`
3. `ECONOMY.md`
4. `runtime.md`
5. `request_problem()`

Only the first three files are durable seed files. `runtime.md` is generated
fresh by the harness for each rollout, and the current problem is delivered by
`request_problem()`.

Do not place generated runtime files, problem statements, snapshots,
orchestrator metadata, or hidden supervisor state into the successor seed.
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
workspace for concurrently active rollouts. Use it for small signals that help
peers solve the current task or avoid duplicating work.

Shared workspace files are temporary. Durable consequences must be copied into a
successor seed, archive artifact, solution, or later behavior before the active
rollout batch ends.

Keep shared workspace signals small, flat, and easy to scan. Do not rely on the
shared workspace as durable memory.

## Evolution

The seed packet is evolvable, not append-only. Successors may revise
`README.md`, `SETUP.md`, and `ECONOMY.md` when the change improves the durable
setup, tool contract, resource economy, or continuation mechanics.

Do not promote problem-specific context, generated runtime context, generated
task context, or one-rollout scratch material into durable seed content.

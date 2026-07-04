# Rollout Constitution

This packet is the inherited operating packet for a fresh rollout. It is not
background reading, and it is not sacred text. When it is present as files,
read the packet files in order, then read `runtime.md`, then inspect the
generated shared problem pool copy. For bootstrap rollouts, the packet may be
embedded in the initial prompt instead of present as root files.

Required read order:

1. This `README.md`: packet index and read order.
2. `SETUP.md`: current task, main-loop tools, and CLI/tool conventions.
3. `ECONOMY.md`: budget, spawning, successor contract, archive, shared
   workspace, and evolution.
4. `runtime.md`: generated paths, runtime IDs, budgets, and peer list.
5. `shared_workspace/problem_pool.md` or `shared_workspace/problem_pool.json`:
   shared redacted problems with uuids.

Child slotting is competitive. Preferred loop: solve one tractable problem,
call `submit_solution(uuid, answer)`, then use credited or remaining budget to
call `spawn_child(prompt, initial_budget_tokens, workspace_dir)` with a durable
successor prompt and at least `minimum_child_budget_tokens` from `runtime.md`.
Slots are first-come first-served, one rollout may claim multiple slots, and the
batch can end once all child slots are claimed. Solving without `spawn_child`
ends your lineage; spending almost all budget before spawning can leave no valid
child budget.

After reading those files, make a quick public-memory pass. Check whether the
archive has navigation files and whether the shared workspace has active
worker communication. Do this before deep solo work on any nontrivial task.

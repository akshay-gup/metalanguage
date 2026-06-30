# Rollout Constitution

This directory is the inherited operating packet for a fresh rollout. It is not
background reading, and it is not sacred text. Read the packet files in order,
then read `runtime.md`, then inspect the generated shared problem pool copy.

Required read order:

1. This `README.md`: packet index and read order.
2. `SETUP.md`: current task, main-loop tools, and CLI/tool conventions.
3. `ECONOMY.md`: budget, spawning, seed contract, archive, shared workspace,
   and evolution.
4. `runtime.md`: generated paths, runtime IDs, budgets, and peer list.
5. `shared_workspace/problem_pool.md` or `shared_workspace/problem_pool.json`:
   shared redacted problems with uuids.

After reading those files, make a quick public-memory pass. Check whether the
archive has navigation files and whether the shared workspace has active
signals. Do this before deep solo work on any nontrivial task.

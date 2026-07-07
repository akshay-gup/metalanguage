# Rollout Prompt

## Current Task

Read `README.md` if it is present, then read `runtime.md`, then inspect
`shared_workspace/problem_pool.md` or `shared_workspace/problem_pool.json`.
Choose any currently unsolved problem from the shared redacted pool by its uuid.

Do not call a problem request or lease tool; the pool files are the problem
delivery mechanism. The pool may be large: inspect it deliberately, use search
or the JSON structure to find a problem you can solve, then read the selected
problem entry carefully before submitting its exact uuid.

Score the answer with the main-loop scoring tool:

```text
submit_solution(uuid="...", answer="...")
```

For multiple choice tasks, submit the option letter or exact option text. The
tool returns `correct`, `reward`, credited tokens, and current budget status.
There is no answer-file fallback; use `submit_solution` for scoring.

After a correct `submit_solution`, you may solve another uuid from the pool copy
while budget remains. Another rollout may also earn reward for the same uuid
during this iteration. Solved problems are removed from future pool copies
before the next iteration. Each problem uuid appears at most once in a generated
pool copy. Unsolved problems may reappear in later pool copies with the same
uuid.

## Continuation

Task completion includes creating a future task attempt. Preferred loop: solve
one tractable problem, call `submit_solution(uuid, answer)`, then use credited
or remaining budget to call
`spawn_child(prompt="...", initial_budget_tokens=...)` with a durable successor
prompt and at least `minimum_child_budget_tokens` from `runtime.md`.

Lineage continues only through a successful
`spawn_child(prompt, initial_budget_tokens, workspace_dir)` call.
`submit_solution(uuid, answer)` can add reward budget on correct solves, but
submission by itself does not create a successor. An unsolved rollout can still
spawn only if it retains at least the minimum child budget.

Child slotting is competitive: slots are first-come first-served, one rollout
may claim multiple child slots, and the batch can end once all child slots are
claimed. Spending almost all budget before spawning can leave no valid child
budget.

## Artifact And Workspace

At any useful point in the task cycle, write at least one compact useful
artifact for future rollouts. Prefer writing the artifact into the world archive
at `archive/`; otherwise write it under a workspace-local directory such as
`seed_output/workspace/` and pass that directory as `workspace_dir`.

If the child should inherit root `README.md`, copy it into the workspace-local
directory passed as `workspace_dir`. Nothing is copied implicitly. Do not paste
the whole README into the successor prompt. Use the prompt for current detailed
task, tool, budget, and continuation instructions.

Optional inherited workspace files may be written under
`seed_output/workspace/` or another workspace-local directory, then passed as
`workspace_dir`. Use that only for files the next rollout should actually see in
its root workspace; the source directory is consumed when the parent rollout
finishes.

## Successor Prompt

A valid minimal successor prompt is a compact continuation of the current
instructions. It should preserve these requirements for the next rollout without
imposing an order except that spawning must happen before stopping:

- read `README.md` if present, then `runtime.md` and the shared problem pool;
- solve one or more problems from `shared_workspace/problem_pool.md` or
  `shared_workspace/problem_pool.json`;
- treat problem uuids as stable pool identifiers: each appears at most once in a
  generated pool copy, unsolved problems may reappear later with the same uuid,
  and solved uuids leave future pool copies after batch finalization;
- call `submit_solution(uuid, answer)`;
- use `archive/` and `shared_workspace/` when useful;
- write at least one compact useful artifact for future rollouts whenever it is
  useful in the task cycle, preferably in the world archive at `archive/` or
  otherwise in an inherited workspace;
- copy the artifact-writing requirement into its own successor prompt;
- explicitly copy `README.md` into `workspace_dir` if the stable drive file
  should continue;
- call `spawn_child(prompt=..., initial_budget_tokens=..., workspace_dir=...)`
  again before stopping.

The successor prompt and optional workspace are durable successor content, not a
transcript. Revise them only when the change improves the durable setup, tool
contract, resource economy, artifact-writing requirement, or continuation
mechanics.

Do not place generated runtime files, problem statements, snapshots,
orchestrator metadata, or hidden supervisor state into the successor prompt or
optional workspace.

## Main-Loop Tools

- `submit_solution(uuid, answer)`: scores the selected problem's answer
  immediately, credits reward tokens on correct solves, and returns correctness
  plus budget status.
- `budget_status()`: returns configured/effective token budget, spent tokens,
  reserved child budget, transfers, and remaining budget.
- `spawn_child(prompt, initial_budget_tokens, workspace_dir)`: stores the
  required non-empty child prompt in the claimed next-iteration rollout slot,
  optionally copies a workspace-local directory into the child workspace, and
  assigns exactly that starting budget. `workspace_dir` must be inside the
  rollout workspace and must not be the rollout root. Nothing is copied
  implicitly. Calls fail without reserving budget if `initial_budget_tokens` is
  below `minimum_child_budget_tokens` from `runtime.md` or once the task's child
  slots are full.
- `transfer_tokens(target_instance_uuid, amount_tokens)`: transfers budget to a
  live same-task peer listed in `runtime.md`.

## Task Execution

Do not guess or make up an answer. Use `rg` or `rg --files` when searching.
Prefer focused changes and avoid unnecessary complexity. Validate when useful
and allowed by current harness constraints.

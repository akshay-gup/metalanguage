# Metalanguage experiment variants

This chronology records the main Riemann-hypothesis research variants and the
variables changed between them. A **valid** run met the acceptance rules in
force for that experiment; it does not imply mathematical correctness or
novelty. No variant proved the Riemann hypothesis, and none used a configured
mathematical evaluator.

## Variant chronology

| Variant | Evidence status | Main variable change | Observed outcome |
| --- | --- | --- | --- |
| Original v1 | Valid | Minimal 71-byte base and fresh prompt pointed to a rich 4,011-byte workspace README. Rollouts had linked worktrees, serial merges, parent-written child prompts and copied child workspaces, with no peer-message bus. | At the matched tasks 0–4 horizon, 40/40 turns produced 30 children and 36 committed rollouts; 28 integrated cleanly, eight conflicted, and 29 committed heads were in canonical ancestry after one later recovery. Its narrower advantage was RH executable evidence and checkability: 42 RH files included 11 Python files and five mathematical test files with 27 tests. |
| CA-v2 | Valid, final HIGH treatment | Stock Codex instructions were retained and the Metalanguage contract was delivered additively through `AGENTS.md`. Sessions were fresh, childless and peerless on one shared checkout. | Five iterations/40 turns explored many proof routes, but produced broad, duplicated exposition and no mathematical tests. It was more exploratory than matched CR-v2, with substantially less consolidation. |
| CR-v2 | Valid, final HIGH treatment; earlier LOW precursor superseded | The same control contract replaced stock base instructions through `model_instructions_file`; all other control mechanics matched CA-v2. | Ten iterations/80 turns converged on a concise, accurate open-problem answer and a useful symmetric-polynomial counterexample. Later work was mainly editorial rather than a deeper theorem program. |
| Peer-enabled current | Valid | Rich instructions moved to system/base priority; vertical child lineage and a same-batch peer-message bus operated on one literal shared Git checkout. | Ten iterations used 80 nominal rollouts but 100 actual turns because peer deliveries added turns. Immediate sharing and clean linear Git improved coordination, then saturated into repeated auditing; the final archive was concise prose with no code/tests. |
| v3 no-peer | Valid under its original protocol; later lifecycle defect found | Removed the peer bus while retaining rich system/base instructions, child lineage and the shared checkout. | Five iterations/40 turns preserved specialization with much less coordination overhead and improved the canonical Li/Newman audit. Shared-checkout races remained, and later inspection found unpolled commands after accepted turns. |
| v3.1 | Valid | Replaced the shared checkout with isolated rollout repositories and deterministic slot-order integration; kept the compact 2,494-byte environment contract at system/base priority and added strict lifecycle draining. | Two iterations/16 turns produced 16 children, ten merges and six preserved conflict refs. Git races disappeared, but duplicated RH answers and a technically solid yet tangential `worldlog` direction dominated much of the durable work. |
| v3.2 | **Partial/invalid as a two-iteration result** | Moved the workspace contract out of base instructions: a 71-byte pointer directed rollouts to the root README, while fresh user text remained `Begin.`. Isolated Git and fail-closed lifecycle checks remained. | Task 0 completed 8/8 with eight children. Task 1 accepted only six of eight turns because two completed with unresolved commands, so it was not integrated or published. Its preserved branches nevertheless contained strong Li recurrence tests, Fourier/Laguerre–Pólya audits and countermodels. |
| v3.3 restored-v1 hybrid | Valid; one earlier missing-host attempt invalid | Restored exact v1 placement and behavior: the 71-byte pointer was both base and fresh user text, the 4,011-byte README lived in the workspace, and linked worktrees, child copying and historical completion semantics returned. Modular OpenCode support remained backend-scoped. | The valid rerun completed 16/16 turns with 15 children, eight clean merges and four conflict refs. It recovered executable Li certificates and finite-prefix, symmetry and Euler-product countermodels. One accepted turn briefly outlived a SymPy command, confirming the historical lifecycle risk. |
| v3.4 | Valid | Changed only the v3.3 workspace README to the exact compact 2,494-byte v3.1 text; v1 prompt placement, linked worktrees, lineage, HIGH effort and no-peer behavior stayed fixed. | Two iterations completed 16/16 turns with 244 tool starts and 13 clean merges. Research activity and integration increased, including Jensen/kernel and positivity reductions, but child continuity fell from seven task-0 successors to only one task-1 successor (eight total). |
| v3.5 | **Partial/invalid run evidence** | Starting from v3.4, restored the v1 continuation contract onto the compact README: child workspace validation, one reserved successor, retry and parent continuation, fresh refill, inherited README obligations and exact tool wording. | Task 0 completed 8/8 with eight children, 71 paired tool calls, five clean merges and two conflict refs. Task 1 reached eight turn-complete events, but only seven rollouts finalized and spawned children; one rollout stopped before archive finalization, leaving 139 tool starts versus 135 completions and no finalized task-1 run-record batch. Partial artifacts include first-Li-coefficient positivity, a finite Li-quartet obstruction, and Jensen/Hutchinson audits. This is suggestive lineage recovery, not a valid two-iteration comparison. |
| v3.6 | **Valid through tasks 0–10; task 9 has a disclosed checkpointed retry outside the matched horizon** | Keeps the v3.5 research turn, README, lineage, backend and linked-worktree behavior unchanged. Only when deterministic Codex/open-ended integration conflicts, the supervisor reconstructs the conflict at the same `archive/` path in a remote-free disposable repository and resumes that exact original session once for a merge-only turn. | At the matched tasks 0–4 horizon, 40/40 turns produced 31 children and 39 committed rollouts. Thirty-two integrated cleanly; seven conflicted, with three resolver integrations and four safe fallbacks; 36 committed heads reached canonical ancestry after one later recovery. Relative to v1 it was similar or better overall in activity and retention, while v1 retained the narrower RH executable/checkability advantage. |
| v3.7 private inbox | **Valid through tasks 0–4** | Preserves v3.6 behavior and adds a pull-based private `messages/` inbox only to Codex/open-ended research turns. One supervisor-backed `send_message(recipient, message)` tool performs direct atomic delivery without supervisor message-size or send-count quotas; sibling inbox reads are denied, and there is no automatic context delivery, broadcast, polling, read API, or peer-bus state. | The matched five-iteration run completed 40/40 turns with 27 children and 39 committed rollouts. Thirty-three integrated cleanly; six conflicted, with three resolver integrations and three safe fallbacks; 36 committed heads reached canonical ancestry. Five task-0 messages were delivered but observably unread, and tasks 1–4 sent none, so no causal inbox benefit was demonstrated. |

## The maintenance attractor

The clearest observed failure of uncoupled propagation comes from outside the
RH variant sequence: a real-task pilot in which rollouts were asked to build a
US researcher outreach list (25 candidates, CSV + report). Over 12 iterations,
rollouts converged on maintaining and extending validator tooling rather than
performing the outreach task itself.

A read-only audit of the run found the pattern was locally rational rather
than random:

- The task as given conflicted with the environment's standing instruction of
  no assigned objective; in the absence of a clear objective gradient, rollouts
  defaulted to the most legible available work — improving the machinery.
- An early lineage's validator artifacts became a self-reinforcing attractor:
  they were referenced in lineage seeds, re-touched through merge conflicts
  (which replenished their recency and visibility), and re-emitted into
  descendant seeds because they were prominent — not because they advanced the
  task.
- Activity measures confirm the shift: 133 network calls in tasks 0–2
  (genuine outreach work), zero in tasks 3–11 (tooling maintenance only).

This is propagation decoupled from usefulness in its pure form: deep
re-emission chains, zero task advancement. It is the empirical case that
motivates the selection-by-uptake account in the theory paper — the system had
amplification (recall → use → re-emission) with no coupling between
amplification and demonstrated helpfulness. Any future selection mechanism must
be tested against this case: it must be able to starve the attractor, not
merely outgrow it.

## What the sequence indicates

- Instruction placement materially changes behavior. Rich system-level
  contracts favored concise status auditing; the workspace-pointer treatments
  in v3.2 and v3.3 recovered more independent, testable research.
- Child lineage amplifies the handoff it receives. Specialist v1/v3.3 prompts
  sustained mathematical programs, while peer-era stewardship prompts
  reinforced consensus. v3.4 showed that merely mentioning a successor was not
  enough to preserve second-generation width.
- Peer messaging improved immediate awareness but was expensive and encouraged
  convergence. Removing it preserved useful specialization without the extra
  delivery turns. The v3.7 pull-based inbox added no turns, but its five sent
  messages were not observably read and therefore showed no coordination gain.
- Git topology is a retention tradeoff. A shared checkout gives immediate,
  linear integration but permits races and coalescing; per-rollout worktrees or
  repositories preserve independence but require explicit conflict recovery.
- Executable certificates and countermodels were the clearest markers of
  checkable depth. They were strongest in original v1, v3.2's preserved
  branches and v3.3, while several concise variants remained prose-only.
- Lifecycle correctness is part of experimental validity. The missing Code
  Mode host invalidated the first restored-v1 attempt; unresolved tools made
  v3.2 task 1 and the v3.5 two-iteration evidence partial. v3.6's task 9
  comparison remains qualified by its disclosed timeout-driven retry.
- Exact-session recovery materially improved retention but was not universal:
  14 of 31 live conflict-resolution attempts passed the clean exact-parent
  merge checks, while the other 17 safely preserved their original refs and
  did not prevent later integrations.

## Growth metrics: four separate measures

Artifact and event counts in the chronology above are reported with the caveat
that they are not token measures, scores, or correctness evidence. That caveat
should be sharpened into a standing measurement plan: growth is not one
quantity, and the components must be tracked separately.

1. **Artifact volume**: how much is produced (files, commits, lines). Measures
   activity, nothing more.
2. **Approach diversity**: how many distinct directions are pursued (distinct
   proof routes, distinct tooling strategies, distinct task framings). Measures
   breadth; convergent chatter scores low here even at high volume.
3. **Depth**: how far the deepest lines go (multi-generation chains, executable
   certificates, countermodels that survive scrutiny). Measures cumulative
   building rather than restarting.
4. **Useful progress**: task-advancing outcomes measured independently of
   propagation — under ablation (does removing the artifact harm descendants?),
   under perturbation, and against held-out assays. Measures what the other
   three do not: whether any of it helped.

The four can diverge sharply, and the divergences are diagnostic. High volume
with low diversity is chatter or ritual documentation. High diversity with low
depth is exploration without accumulation. High depth with low useful progress
is the maintenance attractor — cumulative building on a foundation that serves
the machinery rather than the task. The organizational-transition claim in the
theory paper is a claim about the joint behavior of (2), (3), and (4) with (1)
held bounded: new organizational levels should appear as diversity and depth
converting into useful progress, not merely as more artifacts.

## Generality as a task objective

The variant chronology above concerns object-level tasks: solve these problems,
advance this proof. A distinct task class is the generality task: build a
system that is broadly capable across a problem class, where the agents
discover the necessary organization themselves. The ProgramBench meta-task
("build a reusable system for solving ProgramBench-style tasks") is the first
instance: the objective is not a set of solved examples but a reusable solver,
and the organizational structure — what tools to build, what conventions to
adopt, how to divide the work — is left for the rollouts to invent.

This is a different game from accumulating solutions to supplied examples, and
it must be scored differently. Object-level tasks measure outputs; generality
tasks measure the reusability and breadth of what was built. The ProgramBench
pilot ran two iterations but was never officially scored (the container
dependency was never installed), so it stands as a task-design proposal with
preliminary evidence, not a result. Future generality tasks should be specified
with the same care as the benchmark drivers: what counts as "reusable," on
what held-out distribution, judged by whom.

## Two levels of self-correction

Evaluation must distinguish two levels of correction that the current
measurements conflate:

- **Level 1 — local correction**: a rollout fixes its own errors — failed
  tests, invalid proofs, broken tooling. Visible within a single episode;
  largely a function of base-model capability.
- **Level 2 — agenda correction**: the population abandons unproductive
  directions across generations — drops a dead proof route, retires a tooling
  obsession, reallocates effort. Visible only across lineages; a function of
  the inheritance machinery.

A lineage can be perfect at level 1 and stuck at level 2 indefinitely: every
rollout correctly maintains the validator, and the validator never helps. The
maintenance attractor is exactly this pattern. Falsifiers that test only
level 1 (did descendants fix the errors?) will pass while the system fails at
the thing that matters. Agenda-correction measures — direction turnover across
generations, retirement rate of propagated artifacts, reallocation of effort
after negative evidence — should be tracked alongside local-correctness
measures and reported separately.

## Current source

The tracked source preserves the compact environment wording, restored v1
child-lineage mechanics, minimal pointer placement, normal linked per-rollout
worktrees, and bounded exact-session merge-resolution turn. The v3.7 private
inbox is no longer exposed to active rollouts; its row and results above remain
as historical experiment evidence.

Historically, at the matched tasks 0–4 horizon, v3.7 recorded 1,018 reasoning items and 650
ordinary tools plus five sends, compared with v3.6's 935 reasoning items and
664 ordinary tools and v1's 790 reasoning items and 540 tools. V3.7's final
archive had 28 RH files/5,708 lines and three mathematical Python files,
including one test file with three tests. V3.6 was similar or better overall
than v1 at this horizon because of its activity and much stronger integration;
v1's advantage was narrower but important—more extensive RH executable proof
engineering and mathematical tests. V3.7 improved RH focus and conflict rate
relative to v3.6, but the unused inbox does not establish a communication
effect. These event and artifact counts are not token measures, mathematical
scores, correctness evidence, or an RH-proof claim.

## Restored v1 execution contract (moved from README)

The Codex/open-ended compatibility path is restored from outer source commit
`43ec789` (the last material v1 source used through historical task index 9).
It uses the bootstrap `seeds/bootstrap/AGENTS.md`, the one-character base
placeholder `.`, independent linked Git worktrees and
`rollout/...` branches, copied child workspaces, and serial supervisor merges.
Uncommitted archive edits are discarded; conflicting branches are retained but
not merged. There is no peer-message bus, automatic delivery turn, polling
protocol, private inbox, direct-send tool, broadcast, store, or cursor. The
v3.7 private-inbox experiment remains documented above, but the
active rollout contract no longer exposes it.

OpenCode remains an explicitly selected, separate backend. Its adapter,
protocol metadata, and containment do not alter the Codex request, workspace,
Git, prompt, completion, or cleanup path.

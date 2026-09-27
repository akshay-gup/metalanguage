# Selection by Uptake — Design Note

*Status: proposal. Not implemented. This note turns the selection-by-uptake account (theory paper §6) into buildable mechanism. It is provisional: proposals live here until experiments promote or kill them.*

---

## 1. The mechanism

**Medium.** AGENTS.md files — the root → repository → directory cascade. They are automatically loaded into fresh contexts and rewritten every generation. This is the layer where memory and regulation coincide: the only persistent structure that is both inherited and interpretive.

**Judge.** Uptake and re-emission, nothing else. An artifact's future representation grows if and only if later agents take it up (read it, use it, adapt it) and re-emit it (write it, or a pointer to it, into their own guidance or artifacts). There is no scorer for process artifacts; no verifier grades a seed's doctrine.

**Reproduction number.** Each artifact has an effective reproduction number per generation:

```text
R = E × P(uptake | exposed) × P(re-emit | uptake)
```

- **E** = agents exposed (guidance insertions into live contexts — countable from run logs).
- **P(uptake | exposed)** = fraction of exposures where the agent actually engages (behavioral — see §3).
- **P(re-emit | uptake)** = fraction of engagements that get written back into descendant-facing substrate.

R > 1: the artifact spreads. R < 1: it goes extinct. All three factors are measurable from existing instrumentation plus the uptake logging proposed in §3. This gives the theory's "differential continuation" an operational definition without a fitness function.

## 2. Scarcity: competition needs losers

If agents can hoard unlimited pointers, everything persists and the result is drift, not selection. Competition requires that something actually dies.

**Current state:** context windows are finite (soft scarcity — agents do get overwhelmed), but nothing enforces a guidance budget. An agent may carry forward everything it ever saw.

**Options:**

- **(a) Hard budget.** Cap guidance bytes per directory level. Agents must choose what to keep. Simple, legible, but the cap is arbitrary and agents may game it by compression.
- **(b) Eviction on exit (§3).** Unengaged guidance is dropped when the agent leaves the directory. Scarcity emerges from the filter rather than a number.
- **(c) Decay.** Artifacts not re-emitted within N generations lose visibility or are archived out of the hot set. Addresses long-run bloat; does nothing for within-episode hoarding.

**Recommendation:** (b) as the primary mechanism — it is simultaneously the scarcity enforcer and the uptake measure (§3). (c) as a backstop for the archive.

## 3. Eviction and consolidation (proposal)

The directory guidance lifecycle becomes symmetric: inserted on entry, evicted on exit, with engagement as the filter.

- **On entry:** AGENTS.md is auto-inserted into context (already implemented via the pre-tool gate, Sept 2026).
- **On exit:** the inserted guidance is evicted from context, except what the agent engaged with. What survives the exit is the revealed uptake record — no self-report, nothing to perform for.
- **What counts as "used"** — two signals, both needed:
  - *Textual:* the agent quoted, paraphrased, or explicitly referenced the guidance.
  - *Behavioral:* the agent's actions were consistent with the guidance (e.g., it ran the test suite after reading "run tests before committing," without ever repeating the words). Strict text-matching would lose tacitly-followed guidance, which is often the most internalized kind.
- **Consolidation prompt (proposed):** on directory exit, ask the agent to write down what it wants to retain from that directory's guidance. What it writes is simultaneously the uptake measurement and the re-emission into its own seed. The agent becomes the curator, explicitly.

**Effect.** The lineage seed stops being "whatever the parent chose to write" and becomes "whatever survived uptake across every directory the parent visited" — the bounded lineage seed produced by a real filter rather than parental discretion. The measurement and the mechanism are the same event.

## 4. Open problems

1. **Coupling to usefulness.** The uptake judge rewards propagatability, not quality (§6 of the theory paper). How is re-emission coupled to demonstrated helpfulness without reintroducing a scorer? Candidate direction: consumer-side evidence — uptake associated with downstream task success, measured independently of the artifact's own propagation. Unresolved.
2. **Self-promotion.** A lineage can keep re-emitting its own artifacts, manufacturing R > 1 without any external validation. Candidate mitigations: discount self-lineage re-emission in visibility accounting; require cross-lineage uptake before archive promotion. Unresolved.
3. **What counts as "used."** Textual signals are precise but miss tacit compliance; behavioral signals are broad but hard to attribute. The consolidation prompt sidesteps this by asking directly, but introduces its own performativity risk. Needs experimentation.
4. **Unit of selection.** Whole AGENTS.md file? Section? Individual pointer? Artifact? Finer units allow sharper selection but cost more to track and may fragment coherent doctrine. Unknown.
5. **Cold start.** A new artifact has zero exposures, so R = 0 by definition. How does anything new get its first uptake? Candidate: a small exploration budget — random or round-robin promotion of new artifacts into contexts, analogous to bootstrap exploration for unusual lineages. Unspecified.

## 5. Relation to current code

**Already exists:**
- Directory AGENTS.md auto-loading with pre-execution gate (Sept 18–20).
- `spawn_child` with AGENTS.md-validated workspaces (transactional, one child per rollout).
- Archive worktrees with supervisor-side serial merges.

**Missing (build list):**
- Exit eviction for directory guidance.
- Consolidation prompt at directory exit.
- Uptake logging: exposures, engagements (textual + behavioral), re-emissions — the three factors of R.
- R computation and reporting per artifact.
- Any scarcity enforcement on guidance size (budget, eviction, or decay).
- Cross-lineage uptake accounting for archive visibility.

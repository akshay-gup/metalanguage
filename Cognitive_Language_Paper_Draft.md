# Cognitive Language and Artificial Cultural Evolution

Working reconciliation draft. Source file: `Cognitive language.docx`.

The source DOCX should be treated as read-mostly source material. This document is
the paper-facing workspace: it reconciles the main document and appendix into one
argument, then turns that argument into a draftable paper structure.

## 0. Reconciliation Summary

The current main document and appendix are not two separate theses. They are two
views of the same mechanism at different levels.

The main document is the substrate and constraint view. It asks what structural
conditions make recursive, cumulative improvement possible:

- a plastic process coupled to a persistent substrate
- self-referential representation
- a transmission gap that forces externalization
- finite memory, noisy transmission, bounded reading, and selection pressure
- part-level persistence through named, addressable, reusable units
- a machine model in which a stochastic model and deterministic execution operate
  on the same persistent tape

The appendix is the ecology and heredity view. It asks what must persist across
fresh runs for open-ended improvement to become evolutionary rather than merely
episodic:

- fixed constructor plus mutable culture
- fresh rollout episodes as temporary phenotypes
- lineage seeds as vertical cultural inheritance
- Git/archive artifacts as public cross-lineage culture
- differential persistence through descendant viability, reuse, trust, uptake,
  dependency, and validated downstream usefulness
- separate vertical and global fitness channels

The paper should combine these as a nested model:

1. Substrate theory explains why cumulative recursion needs an external,
   self-referential medium.
2. Constraint theory explains why such media converge toward language-like
   structure.
3. Ecology theory explains why stored structure must face differential uptake and
   consequence, not merely exist in memory.
4. The AI proposal instantiates all three: a stable LLM interpreter population
   operating over persistent files, bounded context, context wipes, deterministic
   tests, lineage seeds, and a public archive.

Concise unified thesis:

> Open-ended recursive self-improvement in LLM systems should not be modeled as a
> lone reasoner rewriting itself. It is better modeled as artificial cultural
> evolution over a stable interpreter population, where fresh-context rollouts
> reconstruct inherited process from private seeds and public archives, act under
> scarcity, and leave transmissible traces that persist only when they help future
> agents continue, adapt, and build further.

## 1. What Each Existing Piece Should Become

### Main Document Contribution

The main document should supply the theoretical spine:

- Only two known recursive accumulation systems: biology and human culture.
- Their shared property: a process can represent and modify its own rules through
  a medium it can also write.
- Plasticity and persistence cannot be maximized in one substrate, so cumulative
  systems split into coupled loops.
- The persistent substrate emerges to solve a bottleneck of the active process.
- Language-like structure is not optional decoration; it is the scalable solution
  to many meanings, finite media, noisy transmission, limited learning, and
  bounded memory.
- LLMs already have strong interpreter machinery, but lack endogenous
  transmission ecology.
- The repo/tape plus bash plus model plus deterministic tests is a plausible
  minimal machine for substrate-level accumulation.

### Appendix Contribution

The appendix should supply the architecture and selection theory:

- The inherited unit is not a prompt, a workspace dump, or literal DNA. It is a
  heritable process packet: whatever causes future fresh-context runs to
  reconstruct useful process.
- Separate fixed constructor from mutable culture.
- Separate workspace, lineage seed, and global archive.
- Separate vertical inheritance from cross-lineage inheritance.
- Git is only storage by default. It becomes ecology only when artifacts compete
  for scarce attention, trust, validation, dependency, and reuse.
- Reuse is meaningful only when coupled to grounding, cost, provenance, and
  downstream performance.
- Open-endedness requires consequence: successful structures must change the
  environment later structures face.

### Integration Rule

The paper should avoid presenting "substrate" and "ecology" as alternatives.
Substrate is the medium that can accumulate. Ecology is the pressure that makes
accumulation selective.

Memory alone gives storage.
Selection alone gives episodic optimization.
Substrate plus selection plus inheritance gives cumulative evolution.

## 2. Reconciled Argument Map

### Claim 1: Recursive improvement requires two coupled loops

Main-body version:

- A plastic reader/writer learns quickly but forgets.
- A persistent substrate stores structure but changes slowly.
- Recursive accumulation requires coupling them.

Appendix version:

- A fixed constructor regenerates agents.
- Mutable cultural inheritance carries learned process across episodes.
- Rollouts are fresh phenotypes that reinterpret and rewrite inherited material.

Paper version:

An AI system needs a stable interpreter and a mutable external culture. The
interpreter supplies plastic search; the culture supplies persistence and
selection-visible inheritance.

### Claim 2: The relevant inherited unit is process, not answer

Main-body version:

- Current RLVR/GRPO selects whole trajectories.
- Without part-level persistence, recurring motifs remain attractors rather than
  replicators.
- The desired unit is reusable procedural structure.

Appendix version:

- The seed is a heritable process packet.
- It includes procedures, evaluators, warnings, archive pointers, usage traces,
  and mutation suggestions.
- A workspace dump is too noisy and a single module is too compressed.

Paper version:

The unit of artificial cultural heredity should be a bounded reconstruction
object: compact enough to transmit, rich enough to regenerate a useful process,
and exposed to descendant success or failure.

### Claim 3: Language-like structure appears when transmission is forced

Main-body version:

- Transmission gaps force discrete, composable, hierarchical representation.
- The MNFL problem explains convergence toward language-like structure.
- Context wipe forces the tape to carry state.

Appendix version:

- Fresh-context episodes must reconstruct inherited process.
- Seeds and archives must be legible under bounded reading and scarce attention.
- Useful artifacts survive only if later agents can interpret and adapt them.

Paper version:

The system should not hand-design a complete DSL. It should engineer the
transmission gap and selection pressures that make compact, modular,
reconstructible process language useful.

### Claim 4: Current systems fail because they lack necessity and consequence

Main-body version:

- Module injection reduced token use but did not raise reward.
- Models mentioned modules without causally using them.
- Artifacts were optional because the base model could solve many problems
  without them.
- The reward landscape was flat among passing solutions.

Appendix version:

- Static benchmark optimization permits improvement without consequence.
- Storage without uptake is not transmission.
- Reuse without grounding becomes memetic drift.

Paper version:

The negative experiments support a structural diagnosis: optional artifacts do
not become evolutionary units. For modules to emerge, later success must depend
on inherited structure, integration must be costly, and downstream use must leave
fitness-relevant traces.

### Claim 5: Git is not the genome; it is closer to public culture

Main-body version:

- Files are named, addressable, persistent parts.
- README-like files can become regulatory layers that direct attention.
- Bounded context creates carrying cost.

Appendix version:

- Git is storage until artifacts face selective uptake.
- Private seeds preserve lineage depth.
- Public archives enable cross-lineage breadth.

Paper version:

The private seed is the vertical channel. The Git archive is the public cultural
channel. A repo becomes an ecology only when future agents must choose what to
read, trust, cite, fork, depend on, and ignore.

## 3. Proposed Paper Shape

### Title Candidates

- Cognitive Language for LLMs
- Artificial Cultural Evolution for Recursive Self-Improvement
- From Self-Modification to Hereditary Process Culture
- Cognitive Language as the Missing Substrate for LLM Accumulation

### Abstract Draft

Open-ended recursive self-improvement is often framed as a single agent
modifying its own mind. This frame misses the structure shared by the only known
systems that have accumulated recursive complexity: biological evolution and
human culture. In both cases, a plastic process is coupled to a persistent
self-referential substrate, and improvement occurs through population-level
variation, selection, retention, and reuse. We argue that LLM systems face an
analogous bottleneck. Modern models already possess strong interpreter
machinery, including in-context adaptation, tool use, code generation, critique,
and procedural reconstruction. What they lack is not merely more memory, but a
transmission ecology in which process artifacts persist, compete, and reshape
future runs. We propose a dual-channel architecture: fresh-context rollout
episodes operate over a persistent file substrate, inherit private lineage seeds,
retrieve public archive artifacts, and are selected by both immediate task
success and downstream usefulness. This reframes recursive self-improvement as
artificial cultural evolution over a stable interpreter population. The framework
explains why prior module-injection experiments reduce token use without
improving reward, why optional memory does not become heredity, and why
language-like process structure should emerge only when context limits,
transmission gaps, scarce attention, and grounded reuse make it necessary.

### Section Outline

1. Introduction: From self-rewrite to hereditary process culture

   - State the failure mode of the lone self-modifying reasoner frame.
   - Introduce biology and human culture as the two known recursive accumulation
     systems.
   - Present the AI thesis: LLMs need a cultural ecology over external process
     artifacts, not just better episodic reasoning.

2. The two-loop structure of cumulative systems

   - Plasticity-persistence constraint.
   - Inner loop: active reader/writer machinery.
   - Outer loop: persistent substrate under selection.
   - Process precedes substrate historically.

3. Why language-like structure converges

   - Define language broadly as discrete, compositional, self-referential
     representation.
   - Present MNFL: many meanings, finite medium, noisy transmission, limited
     learning, bounded memory.
   - Explain why constraints force discreteness, compositionality, hierarchy,
     systematicity, and convention.

4. LLMs as strong interpreters without transmission ecology

   - Existing primitives: ICL, CoT, role, structure, tool use.
   - Why these are native LLM mechanisms rather than failed human analogues.
   - The missing layer: persistent, selectable process inheritance.

5. Why current module systems fail

   - Trajectory-level selection versus part-level persistence.
   - Optional modules and the necessity gap.
   - Module mention theater and broken attribution.
   - Flat verifier landscapes after competence.

6. The artificial cultural evolution architecture

   - Fixed constructor: base model, constitution, tool scaffold, evaluator.
   - Workspace: ephemeral life episode.
   - Lineage seed: vertical culture.
   - Git archive: public cross-lineage culture.
   - Selection: immediate viability, descendant continuity, validated archive
     uptake.

7. The machine instantiation

   - Tape: repo/files.
   - Head: bash read/write interface.
   - Stochastic transition: model proposes patches.
   - Deterministic transition: execution/tests/verifiers.
   - Context wipe as transmission gap.
   - README/index files as regulatory layers.

8. Experimental implications

   - Modules must be necessary, not optional.
   - Reuse must be grounded by downstream success.
   - Future agents should not read everything.
   - Bounded seeds and selective archives should outperform workspace dumps.
   - Success should be measured by multi-generation continuation and cross-lineage
     uptake, not one-step benchmark score alone.

9. Conclusion

   - Recursive self-improvement is an ecological heredity problem.
   - Engineer the substrate, transmission gap, scarcity, and selection channels.
   - Let the process language emerge under pressure.

## 4. Definitions to Stabilize Early

Language:

Discrete, compositional, self-referential representation that can be read,
written, reused, and modified by the same class of machinery that depends on it.
This includes DNA-like codes, human symbolic language, mathematical notation,
programming systems, and possible LLM-native process artifacts.

Interpreter:

The active machinery that reconstructs process from a representation. In the AI
case this is the base model plus scaffold, tools, constitution, and local
context.

Substrate:

The persistent medium on which representations survive across episodes. In the
AI case this is a repo or file system, not the model context.

Transmission gap:

A separation between producer and future consumer that destroys unstored
internal state. Speaker-listener separation, DNA-protein separation, and
fresh-context LLM rollouts all force information to be encoded externally.

Lineage seed:

A bounded inherited process packet passed from parent to child. It is vertical
culture, not DNA and not a full workspace dump.

Archive:

The public shared store from which unrelated lineages can retrieve, adapt,
validate, and depend on artifacts.

Fitness:

Not a single scalar in the paper. Use at least three channels:

- immediate viability: did this rollout solve or improve the task?
- vertical fitness: can descendants reconstruct and continue the useful process?
- archive fitness: do unrelated lineages retrieve, adapt, and benefit from the
  artifact?

## 5. Key Repositioning Decisions

### Reposition "cognitive language"

The phrase should not mean merely "LLMs invent new words." It should mean a
process language for reconstruction: compact external structures that help fresh
LLM episodes reload state, choose actions, use tools, evaluate progress, and
continue improvement.

### Reposition "superlanguage"

"Superlanguage" should be toned down or defined operationally. The more stable
term is "process language" or "heritable process culture." If "superlanguage" is
kept, define it as persistent named reusable process modules plus the conventions
for composing and selecting them.

### Reposition "DNA analogy"

Avoid saying the seed is DNA. The seed is vertical culture. The base model and
scaffold are closer to the fixed constructor. Git is closer to public culture
than genome.

### Reposition "Git"

Git should be introduced as substrate first and ecology only under added
conditions. This resolves the main appendix concern: storing files is not enough.

### Reposition "experiments"

The experimental section should be framed as negative evidence that sharpens the
theory:

- optional modules do not become necessary parts
- adoption is not causal use
- success correlation is not contribution
- workspace persistence creates externalization, but without naming, ranking,
  selection, or scarcity it becomes heterogeneous clutter

## 6. Open Tensions to Resolve Before a Full Paper

1. The word "language" is doing heavy work. The paper needs a precise definition
   early, then must consistently use that definition.

2. The convergence theorem should be stated conditionally. It is strongest as:
   given open-ended content, finite media, noisy or lossy transmission, bounded
   readers, and selection for reuse, scalable systems converge on discrete,
   compositional, hierarchical structure.

3. The reader constraint needs care. Code execution is useful, but if rigid
   scripts become the only reader, the model-reader feedback loop weakens. The
   paper should distinguish tools the model chooses from workflow scripts that
   bypass model interpretation.

4. "Open-endedness" should not be promised from the minimal machine alone. The
   machine creates the substrate and transmission gap. The appendix correctly
   adds that open-endedness also needs ecological consequence.

5. The paper needs a clean experimental claim. The safest claim is not "this will
   create open-ended intelligence," but "this should produce stronger
   multi-generation process accumulation than isolated runs, memory dumps, or
   optional module injection."

## 7. First Paper Draft: Introduction Fragment

Recursive self-improvement is often imagined as an agent that inspects and
rewrites its own mind. That image imports the language of software editing into a
problem that, in nature, has never been solved by an isolated self-modifier. The
only systems known to have accumulated recursive complexity at planetary scale
are biological evolution and human culture. Neither is a single reasoner
improving itself in place. Both are hereditary population systems in which
plastic processes interact with persistent substrates under selection.

This distinction matters for LLMs. Modern models already possess many of the
capacities one would expect from a strong interpreter: they can infer local
rules from context, generate and execute code, critique their own outputs,
summarize evidence, use tools, and reconstruct procedures from written cues. Yet
these capacities mostly die with the episode. Chain-of-thought traces disappear.
Ad hoc tools are not reused. Prompted roles do not form institutions. Memory
stores accumulate text without forcing selection on what future agents actually
use. The result is powerful episodic reasoning without cumulative process
evolution.

The missing object is not memory in the ordinary sense. It is heredity: a
transmission channel through which useful process structure is reconstructed by
future fresh-context runs, varied, tested, and retained only when it improves
future performance. This paper argues that open-ended LLM improvement is better
framed as artificial cultural evolution over a stable interpreter population. In
this frame, a rollout is a temporary phenotype, a lineage seed is vertical
culture, a Git archive is public culture, and recursive improvement occurs when
process artifacts differentially persist because they help later agents continue
and extend them.

## 8. Minimal Experiment Statement

Research question:

Can a population of fresh-context LLM rollouts, given a persistent problem ecology
and bounded heritable seeds, accumulate reusable process structure faster than
isolated rollouts, full workspace carryover, or optional module injection?

Minimal system:

1. Maintain a persistent problem pool.
2. Start every rollout from fresh context.
3. Provide a fixed constitution and tool scaffold.
4. Give each rollout a bounded lineage seed plus a small selected archive slice.
5. Let the rollout work in an ephemeral workspace.
6. Score immediate task progress with verifiers/tests.
7. Let successful rollouts write a bounded next seed.
8. Let rollouts nominate public artifacts.
9. Admit public artifacts using stricter downstream-use evidence.
10. Track vertical and archive fitness separately.

Primary comparisons:

- no memory
- full workspace carryover
- optional module injection
- bounded lineage seed only
- public archive only
- lineage seed plus public archive

Primary measurements:

- multi-generation solve-rate improvement
- seed reconstructibility under fresh context
- descendant viability under perturbation
- cross-lineage artifact adoption corrected by downstream success
- reduction in redundant artifacts
- emergence of stable naming, indexing, or process conventions

## 9. Next Drafting Pass

The next pass should turn this reconciliation into prose, in this order:

1. Abstract and introduction.
2. Definitions and two-loop model.
3. Artificial cultural evolution architecture.
4. Failure analysis of current module experiments.
5. Minimal experiment and falsifiable predictions.

Material that is too speculative for the main line can remain in a later notes
section or separate appendix:

- sexual selection analogies
- detailed pre-RNA chemistry discussion
- broad laws of intelligence
- extended anthropology of writing
- full mathematical formalization of transition functions


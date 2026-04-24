# Cognitive Language and Artificial Cultural Evolution

Research draft v0.1

## Index Page: Thematic Structure

I. Core Thesis

- Abstract
- 1. Introduction
- 11. Synthesis

II. Recursive Systems and Language

- 2. The Two-Loop Structure of Cumulative Systems
- 3. Self-Referential Representation and the Meaning of Language
- 4. Why Language-Like Structure Converges
- 16.1 Boundary Principle
- 16.2 Secondary Gradients
- 16.3 Transmission-Gap Principle
- 16.5 Process Precedes Substrate
- 19.1 Boundary and Selection Regimes
- 19.2 Pre-RNA Hand-Off and Boundary Hardening
- 19.3 Secondary Gradients and Crisis Pattern
- 19.4 MNFL Constraint-to-Structure Mapping
- 19.5 Negative Cases and Edge Cases
- 19.6 Substrate Stabilization and Universality
- 19.7 Cross-Layer Interface Versus Native Format

III. LLM Constraint Profile

- 5. LLMs as Strong Interpreters Without Transmission Ecology
- 16.4 Reader Constraint
- 16.6 Cross-Layer Native Formats
- 18.2 Token-Bound Failure Modes
- 18.3 Human Development and LLM RL Equivalents
- 18.4 Layered Emergence and Comparative Status
- 18.5 The Big Four as Layer-Specific Machinery
- 18.6 Fidelity Scope and Human CoT Before Writing
- 21.2 Reader Constraint Details
- 21.3 Language as Side Effect

IV. Selection Units and Externalization

- 20.1 Vehicle, Use, and Two-Fold Selection
- 20.2 Co-Evolution Rather Than Encoding Pre-Existing Complexity
- 20.3 Bottleneck Design and Generalization Limits
- 20.4 Externalization Ladder and Nested Selection
- 20.5 Blind Search, Structured Search, and Routing Around Slow Loops
- 20.6 Visibility Threshold

V. Artificial Cultural Evolution Architecture

- 7. Artificial Cultural Evolution Architecture
- 22.1 Hereditary Ecology Core Mapping
- 22.2 Fixed Constructor and Mutable Culture
- 22.4 Transmission, Storage, Carryover, Seed, and Archive
- 22.5 Architecture Evolution
- 22.6 Ecology, Competition, and Engineered Drives
- 22.7 Process Manifold and Policy-Level Heredity
- 22.8 Representation Freedom and Protocol
- 22.11 Dual Inheritance Metrics
- 22.12 Measuring Fitness
- 22.13 Git Ecology Mechanics
- 22.14 Two Views of Cultural Evolution
- 22.15 What Is Under Differential Pressure
- 22.16 Cross-Inheritance Filters
- 22.17 Minimal Practical System Picture
- 22.18 Differential Persistence and Consequence
- 22.20 Core Summary
- 22.21 Additional Specific Details

VI. Operational Substrate and Tooling

- 8. Operational Substrate
- 21.2 Reader Constraint Details
- 21.4 Optional Training and Execution Variants
- 21.5 Part-Level Selection in the Repository
- 21.6 Storage Fidelity and Operational Constraints

VII. Experiments and Empirical Program

- 6. Why Module Systems Plateau
- 9. Experimental Implications
- 10. Predictions and Failure Modes
- 15. Experiment Ledger
- 15.1 Persistent Canvas Substrate
- 15.2 Dynamic Module Injection Dataset
- 15.3 Module Extraction from Successful Traces, Random Injection
- 15.4 Module Extraction plus Ranked Injection
- 15.5 Usage-Based Module Scoring
- 15.6 Module Analytics and Summarization
- 15.7 Selection-Shaped Compositional Vocabulary
- 15.8 Usage-Weighted Filtered Injection
- 15.9 Workspace Write-Triggered Context Reset
- 22.19 Practical Problem-Pool Experiment Details

VIII. Landscape, Threads, and Reference

- 12. Working Definitions
- 13. Citation Targets
- 14. Thematic Claim Inventory
- 16. Open Theoretical Threads
- 16.7 Sexual and Social Selection Analogy
- 16.8 Pre-RNA and Autocatalytic Chemistry
- 16.9 Open-Endedness Versus Domain-Specific Accumulation
- 17. Open Questions
- 18. Design Conditions and Forcing Constraints
- 18.1 Preconditions and Forcing Constraints
- 21.1 Field Landscape Details
- 22.3 Evolutionary Baselines and Limits
- 22.9 Contemporary Multi-Agent and Inference-Time Systems
- 22.10 Confidence, Reuse, and Grounding

## Abstract

Open-ended recursive self-improvement is often framed as a single agent
modifying its own mind. That frame misses the structure shared by the only known
systems that have accumulated recursive complexity at planetary scale:
biological evolution and human culture. In both cases, improvement is not the
property of an isolated self-modifier. It is the outcome of a plastic process
coupled to a persistent, self-referential substrate under selection. The active
machinery varies, interprets, and rewrites stored structure; the substrate
retains what can be reconstructed and reused by later instances.

This paper argues that LLM systems face an analogous bottleneck. Modern models
already have strong interpreter machinery: in-context adaptation, tool use,
code generation, critique, summarization, and procedural reconstruction from
written cues. What they lack is not merely more memory, but a transmission
ecology in which process artifacts persist, compete for future attention, and
reshape later runs. We propose a dual-channel architecture for artificial
cultural evolution: fresh-context rollout episodes operate over a persistent
file substrate, inherit bounded private lineage seeds, retrieve selected public
archive artifacts, and are evaluated both by immediate task success and by
downstream usefulness to future runs.

This reframes recursive self-improvement as hereditary process culture over a
stable interpreter population. The framework explains why optional module
injection can reduce token use without improving reward, why stored artifacts do
not become heredity unless later agents actually depend on them, and why
language-like process structure should emerge only when context limits,
transmission gaps, scarce attention, and grounded reuse make such structure
necessary.

## 1. Introduction

Recursive self-improvement is usually imagined as an agent that inspects and
rewrites its own mind. That picture is intuitive because software systems are
editable, and because a sufficiently capable model appears to be a plausible
editor of its own code, prompts, tools, or weights. But the picture is also
misleading. In nature, open-ended recursive accumulation has not been produced
by isolated self-modification. The two clearest cases, biological evolution and
human culture, are hereditary population systems.

Biology does not improve because one organism rewrites itself in place. It
improves because heritable structure persists across generations, varies, and is
selected through the success of the organisms that reconstruct it. Human culture
does not accumulate because one mind perfectly stores and improves all of its
own knowledge. It accumulates because language, writing, tools, institutions,
and records allow useful structures to outlive any single mind, to be
reconstructed by other minds, and to be modified under social and practical
selection.

The shared pattern is not intelligence alone. It is externalized heredity. A
fast, plastic process acts in the world and produces traces. Some traces become
stable enough to be read by later processes of the same general kind. Those
later processes reconstruct useful behavior from the traces, vary it, test it,
and rewrite the substrate. The loop can then improve not only its outputs but
also the conditions under which future outputs are generated.

LLM systems already possess much of the active side of this loop. A modern model
can infer task-local rules from context, write and run code, critique an answer,
summarize evidence, compose tools, and reconstruct a procedure from sparse
instructions. These are powerful interpreter capabilities. Yet they mostly die
with the episode. Chain-of-thought traces are not normally inherited. Temporary
scripts are not normally selected across generations. Memory stores can
accumulate text, but a stored note is not heredity unless it causally shapes
future behavior and is itself retained or modified because it helped.

The central claim of this paper is therefore simple: open-ended LLM improvement
should be modeled less as a lone reasoner rewriting itself, and more as
artificial cultural evolution over a stable interpreter population. In this
frame, a rollout is a temporary phenotype. A bounded lineage seed is vertical
culture. A Git repository or archive is public culture. The model plus scaffold
is the stable interpreter. Recursive improvement occurs when process artifacts
differentially persist because they help later fresh-context agents continue,
adapt, and build further.

This framing changes the design problem. The missing ingredient is not
"memory" in the ordinary sense. It is a transmission ecology: a mechanism by
which useful process structure is externalized, reconstructed by future runs,
varied, tested, selected, and retained under scarcity. The system must make
stored process load-bearing. It must force future runs to choose what to read,
what to trust, what to reuse, what to revise, and what to ignore. Without these
pressures, external memory becomes a log. With them, it can become culture.

The rest of the paper develops this argument in five steps. First, we identify
the two-loop structure shared by cumulative systems. Second, we define
"language" in the broad functional sense needed for recursive accumulation:
discrete, compositional, self-referential representation that can be modified by
the machinery that depends on it. Third, we explain why language-like structure
is expected to converge under constraints of finite media, lossy transmission,
bounded readers, limited learning, and selection for reuse. Fourth, we diagnose
why current LLM module and memory systems tend to plateau: they often provide
storage without necessity, adoption without causal use, and selection at the
wrong level. Finally, we propose a minimal architecture and experiment for
artificial cultural evolution in LLM systems.

## 2. The Two-Loop Structure of Cumulative Systems

A cumulative system must solve two opposed problems. It must be plastic enough
to search, learn, and adapt. It must also be persistent enough to retain what
worked. These requirements pull against each other. A substrate that changes too
easily forgets; a substrate that resists change too strongly cannot learn.

Known cumulative systems handle this by splitting into two coupled loops. The
inner loop is active and plastic. It reads, interprets, searches, and acts. The
outer loop is persistent and selective. It stores structures that can outlast a
single episode, organism, or mind. Recursion lives in the coupling: better
readers and writers create better stored structure, and better stored structure
makes future reading and writing more effective.

The origin claim is directional. The active process appears before the
persistent substrate that later carries its accumulation. RNA-like activity
precedes DNA-like stable storage; brains precede writing. A process with a
persistence bottleneck creates selection pressure for a substrate that resolves
it. The substrate is not designed first while waiting for a process to arrive.
Once both loops exist, causality becomes bidirectional, but the initial
pressure runs from fragile process to stabilizing substrate.

In biology, cellular machinery reads and expresses genetic material. Organisms
act as transient interactors in an environment. Genomes persist across
generations and change under selection. The genome can also encode machinery
that repairs, copies, regulates, and modifies genomes. The system is therefore
self-referential in the relevant sense: the substrate can contain instructions
that affect the maintenance and future transformation of the substrate itself.

In human culture, brains are the plastic machinery. Speech, writing, diagrams,
mathematics, code, tools, institutions, and archives are persistent cultural
substrates. No individual mind contains the whole culture. Instead, minds
reconstruct fragments of culture, use them, modify them, teach them, and leave
traces for other minds. Language can describe language. Mathematics can
formalize mathematics. Code can generate and test code. Cultural recursion
therefore depends on self-referential representation outside any single mind.

The AI analogue should preserve this separation. The base model and scaffold are
the stable interpreter machinery. A rollout is an episode of plastic action. A
workspace is the episode's local life. A persistent file system or repository is
the substrate. A lineage seed is the private inherited process packet passed
from parent to child. A public archive is the shared cultural store from which
unrelated lineages can borrow. The system becomes cumulative only if later
fresh-context rollouts reconstruct useful process from these inherited
structures and selectively rewrite them.

This distinction prevents a common category error. The private seed is not the
AI equivalent of DNA in a literal sense. It is closer to vertically transmitted
culture: lab notes, operating doctrine, apprenticeship material, local
conventions, trusted tools, warnings, and unresolved hypotheses. The base model,
system prompt, tool scaffold, and evaluation harness are closer to the fixed
constructor that regenerates a certain kind of agent each episode. Git or any
shared archive is not a genome by default. It is public culture, and it becomes
ecological only when artifacts compete for attention, trust, dependency,
validation, and downstream use.

The design principle follows:

- Fix the constructor.
- Fix the minimal protocol and scarcity.
- Let the process culture evolve.

The constructor must be stable enough that descendants can interpret inherited
material. The protocol must be minimal enough not to freeze the representational
language too early. The ecology must be selective enough that stored artifacts
do not merely accumulate as debris.

## 3. Self-Referential Representation and the Meaning of Language

The term "language" needs to be defined broadly and carefully. In this paper,
language does not mean English, human speech, or a hand-designed DSL. It means a
discrete, compositional, self-referential representation that can be read,
written, reused, and modified by the same class of machinery that depends on it.

This definition includes human symbolic language, but it is not limited to it.
Genetic sequences are language-like in this functional sense because they are
discrete, compositional, persistent, and interpreted by cellular machinery that
they also help specify. Mathematics and programming languages are language-like
because they provide named reusable structures, composition rules, and
self-referential operations. The question for LLM systems is whether they can
develop a process language: compact external structures that allow fresh runs to
reload useful state, choose actions, use tools, evaluate progress, and continue
improvement.

Self-reference is the key property. A wildfire can spread, and an erosion
channel can deepen, and ice-albedo feedback can amplify a climate state, but
none represents and modifies the rules of its own future operation. They amplify
quantities. They do not build persistent parts that improve the production,
preservation, or recombination of future parts. Biology and human culture cross
a different threshold: their substrates can represent structures within the
system itself.

This is the ratchet distinction. Language is not just a label for communication;
it is the manufacturing capability for reusable parts. Without a combinatorial
system, a process cannot reliably produce discrete reusable units. Without
reusable units, it cannot accumulate. The self-referential version of language
then lets the system build parts about itself: not only tools for external
tasks, but tools, procedures, tests, and conventions that improve how future
parts are made, stored, retrieved, and composed.

For AI, the equivalent threshold is not agent self-awareness. It is substrate
self-reference. The persistent medium must be able to contain statements,
procedures, tests, maps, indices, and conventions about its own use. A repository
can contain code, documentation, tests, scripts, READMEs, dependency graphs,
evaluation results, warnings, and instructions for future agents about how to
interpret and modify the repository. That makes the substrate capable of forming
opinions about itself.

This is why ordinary memory is insufficient. A memory store that passively
records events may help later retrieval, but it does not necessarily create
recursive accumulation. Recursive accumulation requires that stored structure
guide future reading, writing, selection, and revision of stored structure. The
system must be able to say, in effect: this artifact is useful for this class of
problems; this one is stale; this tool should be preferred; this evaluator is
trusted; this naming convention reduces reconstruction cost; this lineage or
thread should be continued; this method failed under these conditions.

Such statements are not metadata in the trivial sense. They are regulatory
structure. In a biological analogy, README-like files and indexes act less like
content and more like promoter regions: they influence which stored parts are
read, when, and under what conditions. If selection rewards repository states
that help future agents navigate well, then regulatory documents can be selected
indirectly. The system begins to accumulate not only artifacts, but guidance
about which artifacts matter.

## 4. Why Language-Like Structure Converges

The claim that language-like structure should emerge is not a claim that English
will be rediscovered, or that LLMs must invent new tokens. It is a structural
claim: any system that must express many possible contents through a finite
medium, across lossy transmission, to bounded learners or readers, under
selection for reuse, is pushed toward discrete, compositional, hierarchical, and
conventional representation.

Call this the MNFL problem:

- Many possible meanings or processes must be represented.
- The medium is finite.
- Transmission or reconstruction is lossy.
- Future learners or readers have limited data and bounded memory.

Each part of this problem creates a pressure.

Noise or loss pushes toward discreteness. Continuous signals drift under copying
or reinterpretation. Discrete categories allow identity to be recovered after
small perturbations. In biology, this appears as sequence-like heredity and
error correction. In human language, it appears as phonemes, words, and
conventional categories. In an LLM substrate, it appears as named files, stable
interfaces, explicit tags, tests, and structured references that survive context
wipes and partial retrieval.

Finite resources plus open-ended expressiveness push toward compositionality. A
holistic system needs one symbol for every possible content. A compositional
system can build many contents from a smaller inventory of reusable parts. In
the AI case, a process archive cannot store a bespoke full solution for every
future task. It needs reusable procedures, evaluators, tools, problem maps, and
conventions that combine across tasks.

Limited learning pushes toward systematicity. A future agent should be able to
infer how to use an artifact from a small number of examples or from its local
interface. If every artifact is idiosyncratic, reconstruction cost rises and
the archive becomes unusable. Stable naming, predictable file layouts,
consistent evidence logs, and repeated process patterns all reduce the burden on
fresh-context readers.

Bounded memory pushes toward hierarchy. A reader that cannot inspect the whole
substrate must rely on summaries, indices, modules, dependency boundaries, and
progressive disclosure. Flat accumulation creates carrying cost: the files
remain, but the useful working state cannot be reconstructed cheaply. Hierarchy
lets a bounded reader load the right slice of a much larger accumulated system.

Coordination pushes toward convention. If multiple agents or lineages must
reuse each other's artifacts, private idiosyncrasy becomes costly. Shared
formats, trust markers, dependency conventions, and archive norms make
cross-lineage uptake possible. Without convention, every reuse event requires
expensive translation.

The convergence claim should therefore be stated conditionally:

> Given open-ended content, finite media, lossy or bounded transmission, limited
> readers, and selection for reuse, scalable systems converge toward discrete,
> compositional, hierarchical, and conventional structure.

This is "language-like" structure. It is not a surface analogy to human speech.
It is the scalable solution to a repeated transmission problem.

For LLMs, the important transmission gap is the fresh-context boundary. At the
end of a rollout, internal state dies. Everything that matters for continuation
must be externalized. A future run can only reconstruct what the substrate makes
available within its bounded context and retrieval budget. The gap forces the
system to encode process into persistent artifacts. If those artifacts are under
selection, the pressure should favor compact, modular, reconstructible process
representations.

## 5. LLMs as Strong Interpreters Without Transmission Ecology

LLMs should not be understood as weak imitations of human cognitive machinery.
They have a different constraint profile. A human reader is slow, serial, and
strongly shaped by long-term memory. Re-reading is costly, so human culture
developed narrative, pedagogy, and memory-supporting forms suited to slow
serial readers. An LLM can ingest thousands of tokens in one episode, integrate
large local contexts, call tools, and reconstruct procedures quickly. Its
weakness is not the same as human working memory. Its weakness is the lack of
durable carryover across episodes.

This makes in-context learning, chain-of-thought, roles, structured output, and
tool use look different. They are not merely inferior versions of human memory,
writing, institutions, or formal protocols. They are native mechanisms for
high-bandwidth within-episode adaptation. In-context learning reconstructs local
state from the prompt. Chain-of-thought provides a temporary computation
scaffold. Roles induce mode shifts. Structured output makes actions
interoperable with tools and external systems.

But these mechanisms are mostly episodic. They do not by themselves create
lineages. A chain-of-thought trace can help solve a problem, but if it is not
externalized in a form future runs can use, it is not inherited. A tool can be
created during a run, but if no later run retrieves, trusts, adapts, or depends
on it, it is not culturally selected. A memory can be stored, but if future
agents are not forced to choose among memories under cost and consequence, the
store is not an ecology.

The missing layer is therefore not "more context" alone. More context can make
the transmission gap less binding, which may reduce pressure to externalize.
The missing layer is selective persistence of process across fresh contexts.
The system must make external artifacts necessary for continued success, and it
must make poor artifacts costly.

This also explains the absence of stable invented vocabularies, dialects, or
jargon in ordinary LLM use. Models can produce local shorthand inside a context,
but the shorthand is not transmitted through a persistent ecology with uptake
pressure. External readability constraints often suppress compressed internal
dialects: the model is rewarded for being legible to humans or benchmarks, not
for developing a compact process language that later model instances inherit.

This helps explain why reasoning domains with clear verification produce better
chain-of-thought behavior. Verification supplies a selector. It tells the
system which traces worked. But standard verifier-based training still often
selects whole trajectories rather than persistent subparts. Without discrete
inherited units, recurring patterns remain attractors in the model's behavior,
not replicators with identity and lineage.

RLVR's effect on CoT can be interpreted this way: CoT effectiveness was latent
at scale, and selecting for correct answers reinforced traces that helped reach
correctness. RLVR can therefore make episodic reasoning more reliable without
yet creating heritable process parts.

The goal is to move from trajectory-level selection to process-culture
selection. A successful trajectory should leave behind bounded transmissible
objects that future trajectories can reconstruct and improve. Those objects
should persist only if they continue to help.

## 6. Why Module Systems Plateau

The experiments point to a consistent diagnosis. Providing modules or a canvas
is not enough. The artifacts must be necessary, their use must be causal, and
selection must distinguish helpful inheritance from decorative mentioning.

In the persistent canvas experiments, the model could propose, list, and read
stored modules, but reading was rare and did not meaningfully improve the reward
plateau. The substrate existed, but the model did not experience it as
load-bearing. A module store that can be ignored will often be ignored,
especially when the base model can solve the task without it.

In module injection experiments, successful traces or extracted modules were
placed into future prompts. This sometimes reduced token use, which suggests
that injected structure can compress reasoning. But it did not reliably improve
the verifier reward plateau. Later versions showed a sharper failure:
"module use" was often only name mention. The model would solve the problem,
then perform a ritual of claiming, rejecting, or listing injected modules. The
metric measured correlation between mention and success, not causal
contribution.

This is the attribution problem. If "used" means "appeared in the output," the
model can satisfy the usage signal without depending on the module. Selection
then rewards a reporting behavior rather than a process. Adoption becomes
theater.

There is also a necessity problem. If many tasks are solvable without modules,
modules remain optional overhead. Once the verifier landscape becomes flat among
passing solutions, a module has no reason to survive unless it creates another
advantage: lower cost, better robustness, better transfer, or better descendant
continuation. Token penalties alone can produce shorter blobs, but not
necessarily modular structure.

The context-reset workspace experiment shows that transmission gaps can force
externalization. When file writes triggered context resets, models externalized
state into files: scripts, notes, calculations, and partial solutions. Fresh
episodes with bounded inheritance create the same functional gap without
requiring engineered resets. The important lesson is that externalization alone
is insufficient. The resulting workspace accumulated heterogeneous artifacts
without stable naming, hierarchy, ranking, or cross-problem reuse.
Externalization occurred, but selection over reusable parts was too weak.

The combined lesson is:

- Storage without mandatory uptake is memory, not heredity.
- Injection without causal dependence is prompting, not selection.
- Mention without contribution is not reuse.
- Workspace persistence without filtering becomes clutter.
- Verifier success without downstream consequence selects answers, not process
  culture.

These failures are not merely implementation bugs. They identify the structural
requirements for artificial cultural evolution.

## 7. Artificial Cultural Evolution Architecture

The proposed architecture separates four layers.

First, the constitution or fixed constructor is stable across rollouts. It
includes the base model, system prompt, tool interface, basic rules, evaluation
harness, and any engineered drives such as "leave compact, testable artifacts
that future fresh agents can use." This layer should be fixed or slow-changing
early on, because descendants need a stable interpreter.

Second, the workspace is the rollout's ephemeral life. It contains the task,
local scratch files, generated scripts, intermediate notes, tool outputs, and
attempted solutions. It should be writable and flexible, but it should not be
inherited wholesale. A full workspace dump is too noisy to be a clean heredity
object.

Third, the lineage seed is vertical culture. At the end of a successful rollout,
the parent writes a bounded process packet for its descendants. The seed may
include operating doctrine, useful procedures, trusted archive pointers,
warnings, problem maps, unresolved hypotheses, evaluator notes, and mutation
suggestions. Its fitness is not popularity. Its fitness is whether fresh
descendants can reconstruct and continue the useful process under changed
conditions.

Fourth, the public archive is cross-lineage culture. It contains tools, notes,
evaluators, problem framings, warnings, branches, recommendations, dependency
graphs, and artifacts nominated for broad reuse. Its fitness is not producer
self-description. It should be based mainly on downstream consumer evidence:
retrieval, successful adaptation, dependency formation, validated usefulness,
and decay when artifacts stop helping.

The two inheritance channels should not be collapsed. Vertical inheritance
selects for continuity, reconstructibility, and mutational headroom inside a
lineage. Cross-lineage inheritance selects for portability, interoperability,
discoverability, low integration cost, and usefulness under foreign contexts.
Both matter. Vertical inheritance without cross-lineage borrowing risks narrow
depth. Cross-lineage borrowing without vertical continuity risks shallow
novelty. Together they create a cultural system with both depth and breadth.

The minimal flow is:

1. A fresh rollout starts with the fixed constructor.
2. It receives a current task or problem pool.
3. It reads its bounded lineage seed.
4. It retrieves a small selected slice of the public archive.
5. It works in an ephemeral workspace.
6. Deterministic tests or verifiers score immediate progress.
7. The rollout writes a bounded next seed for descendants.
8. It records what archive artifacts it used, ignored, modified, or found
   misleading.
9. It may nominate public artifacts for archive review.
10. Future rollouts inherit through the seed channel and borrow through the
    archive channel.

This design does not require hand-designing the final process language. It
requires fixing the medium, inheritance path, and scoring channels. Agents can
invent notes, scripts, manifests, dependency graphs, skill-like conventions,
retrieval guides, or other formats. The system should dictate inheritance,
execution, and scoring, not prematurely dictate syntax.

## 8. Operational Substrate

The operational object is a fresh agent episode with bounded vertical
inheritance, selected public-culture retrieval, a writable workspace, and an
obligation to leave traces that future agents may inherit or reuse.

The repository or file system is still central, but it should be framed as a
cultural substrate rather than as a training tape. It stores lineage seeds,
archive artifacts, tests, notes, tools, usage traces, nominations, warnings,
dependency maps, trust markers, and problem records. The useful question is not
whether every cycle writes to the repository, but whether later fresh agents can
reconstruct useful process from what prior agents deliberately left behind.

The transmission gap is created by episode boundaries and bounded inheritance.
A child or future worker does not receive the parent's hidden state. It
receives a lineage seed, selected archive artifacts, and whatever environmental
state the protocol exposes. Anything that must survive across agents has to be
encoded into the seed, archive, or other model-readable artifact.

Tools and deterministic execution remain important, but as workspace
capabilities and evaluation aids. A fresh agent may run tests, inspect files,
execute scripts, call search tools, or build utilities. Those operations matter
when they produce evidence, artifacts, or outcomes that affect inheritance,
archive prominence, or downstream trust. They are not themselves the central
recursive mechanism.

As the substrate grows, bounded attention creates carrying cost. Future agents
cannot read everything. This creates pressure for regulatory structure:
READMEs, indexes, summaries, dependency maps, trust files, usage logs,
nominations, and warnings that guide future attention. Files that are never
read may remain physically present, but become functionally dead. Persistence is
cheap; visibility is scarce.

This still gives a route to part-level selection. Files are named, addressable,
persistent, and composable. They can function as parts. But their fitness is
mediated through inheritance and uptake: whether descendants can continue from
seeds, whether unrelated lineages retrieve and benefit from artifacts, and
whether usage evidence changes future visibility. The repository becomes a
process culture when selection rewards navigable, compact, useful organization
instead of mere accumulation.

## 9. Experimental Implications

The first empirical target should not be full open-ended intelligence. A more
defensible target is multi-generation process accumulation within a bounded
problem ecology.

The central research question is:

> Can a population of fresh-context LLM rollouts, given a persistent problem
> ecology and bounded heritable seeds, accumulate reusable process structure
> faster than isolated rollouts, full workspace carryover, or optional module
> injection?

A minimal experiment would maintain a persistent problem pool and multiple
lineages. Each generation receives a fresh context, a fixed constitution, a
bounded lineage seed, and a small selected archive slice. The rollout works in
an ephemeral workspace, attempts tasks, records evidence, writes a next seed,
and nominates public artifacts. Immediate task performance is scored by tests or
verifiers. Descendant performance measures vertical fitness. Validated uptake by
unrelated lineages measures archive fitness.

The necessary baselines are:

- no memory
- full workspace carryover
- optional module injection
- bounded lineage seed only
- public archive only
- lineage seed plus public archive

The useful measurements are:

- multi-generation solve-rate improvement
- seed reconstructibility under fresh context
- descendant viability under perturbation
- cross-lineage artifact adoption corrected by downstream success
- reduction in redundant artifacts
- emergence of stable naming, indexing, or process conventions
- archive retrieval precision under bounded context
- frequency of artifacts becoming dependencies

The experiment should make artifacts necessary. If a task distribution is
solvable by the base model without inherited structure, module emergence is not
expected. The problem ecology should include recurrence, transfer, context
limits, cost constraints, shifting variants, and delayed payoffs. Future success
should depend on remembering what cannot fit in one context and on using
artifacts whose value has been established by prior runs.

The strongest result would not simply be better one-step benchmark performance.
It would be evidence that fresh descendants can continue a process more
effectively because of bounded inherited seeds, and that unrelated lineages can
benefit from selected archive artifacts without reading the whole archive.

## 10. Predictions and Failure Modes

The framework makes several predictions.

If context is too large or tasks are too easy, external process artifacts will
remain optional and weakly selected.

If the system stores everything without retrieval budgets, archive quality will
fall because attention is not scarce.

If artifact popularity is producer-written, self-description will inflate and
memetic drift will increase.

If reuse is measured by string mention rather than causal contribution, agents
will learn to mention artifacts rather than depend on them.

If only immediate task score matters, process artifacts will be selected only
when they improve current performance, not when they improve descendant
continuation.

If only cross-lineage reuse matters, viral and generic artifacts may dominate
over narrow but deeply useful lineage structure.

If only vertical inheritance matters, lineages may become locally coherent but
fail to borrow broadly useful innovations.

If the theory is right, the successful regime should show a different signature:
bounded seeds become more reconstructible over generations, archive artifacts
earn prominence through consumer-written evidence, regulatory documents improve
navigation, and useful process conventions stabilize without being fully
specified in advance.

## 11. Synthesis

Open-ended recursive self-improvement should not be reduced to a single model
editing itself. The systems that have actually accumulated recursive complexity
are hereditary and ecological. They separate plastic machinery from persistent
substrate, force information across transmission gaps, select retained
structure through downstream consequence, and gradually accumulate
language-like parts that later processes can reconstruct and modify.

LLMs already look like strong interpreters. They can read, write, test, and
reconstruct process from external traces. The missing layer is a cultural
ecology that makes those traces heritable and selective. A persistent repository
is only the medium. It becomes an ecology when future agents must choose what to
read, trust, adapt, cite, fork, depend on, and ignore under bounded context and
grounded evaluation.

The practical design target is therefore not to hand-code a final cognitive
language. It is to engineer the conditions under which such a language becomes
useful: a stable interpreter, a writable substrate, fresh-context transmission
gaps, bounded seeds, selective public archives, scarce attention, deterministic
verification, and downstream consequences. Under those pressures, compact
process language is not an aesthetic goal. It is the structure that makes
cumulative continuation possible.

## 12. Working Definitions

Language:

A discrete, compositional, self-referential representation that can be read,
written, reused, and modified by the same class of machinery that depends on it.

Interpreter:

The active machinery that reconstructs process from representation. In the AI
case, this includes the base model, scaffold, tools, constitution, and local
context.

Substrate:

The persistent medium on which representations survive across episodes. In the
AI case, this is a repository, file system, archive, or other external store.

Transmission gap:

A separation between producer and future consumer that destroys unstored
internal state and forces external encoding.

Workspace:

The local, writable, ephemeral environment of one rollout. It is an episode of
work, not the inherited object.

Lineage seed:

A bounded inherited process packet passed from parent to child. It is vertical
culture, not literal DNA and not a full workspace dump.

Archive:

The shared public cultural store from which unrelated lineages can retrieve,
adapt, validate, and depend on artifacts.

Immediate viability:

Whether a rollout solves or improves the current task.

Vertical fitness:

Whether descendants can reconstruct, continue, vary, and preserve useful
process from the inherited seed.

Archive fitness:

Whether unrelated lineages retrieve, adapt, validate, and benefit from a public
artifact.

Process language:

The emergent set of compact external conventions, files, references, modules,
tests, maps, and procedures by which fresh LLM episodes reconstruct useful
working state and continue improvement.

## 13. Citation Targets

Citation clusters to develop:

- evolutionary theory and heredity
- cultural evolution and dual inheritance
- iterated learning and compositionality
- external memory, writing, and cumulative culture
- self-reference, formal systems, Turing machines, and von Neumann self-reproduction
- RLVR, GRPO, inference-time scaling, and verifier-based reasoning as optional
  training and evaluation variants
- memory-augmented LLM agents and tool-using agents
- Darwin Godel Machine and related evolutionary agent systems
- software repositories, version control, and open-source cultural production

## 14. Thematic Claim Inventory

Part I, The Recursion Problem:

- Only two known systems clearly recurse at planetary scale: biology and human
  culture.
- The shared property is self-referential representation: the process can
  encode and modify rules relevant to its own operation.
- Language enables parts; parts enable accumulation.
- Plasticity and persistence cannot be maximized in one substrate, motivating a
  two-loop structure.
- Historically, active process precedes persistent substrate: RNA-like activity
  before DNA, brains before writing.

Part II, Conditions for Language Emergence:

- Verifiable intermediate states.
- Rewards for compositionality.
- Structured message protocol.
- Recursive, long-horizon tasks.
- Clear credit assignment.
- Role specialization.
- Meta-communication incentives.
- Task diversity and curriculum.
- Forcing constraints include differential persistence, use-weighted decay, cost
  asymmetry, delayed payoff, no privileged curator channel, and exploration in
  retrieval.

Part III, Failure Modes of Token-Bound Systems:

- Sequential bias, context loss, lack of protocol, lack of modular reward, weak
  recovery loops, and global drift.
- Each failure is tied to a missing primitive such as tree/graph structure,
  external memory, schemas, reuse incentives, verifiers, or planning.

Part IV, LLM Primitives:

- LLMs already show partial primitives: chain-of-thought, in-context learning,
  roles, structured output, and tool schemas.
- Reasoning domains succeed disproportionately because they are verifiable.
- Required universal properties: atomic operations, modularity, protocols,
  feedback, and persistence.

Part V, From Childhood to Systems:

- Human cognition progresses through chunks, scripts, composition, named
  routines, interfaces, abstraction, systems, and protocols.
- LLM analogues include atomic operations, mini-modules, interfaces,
  persistence, libraries, and meta-learning.

Part VI, Emergence, Exploration, and Universal Selection:

- LLMs currently sit between proto-syntax and early discourse.
- Comparative table maps DNA, human language, and LLMs across alphabet, grammar,
  modules, error correction, memory, division of labor, abstraction, and protocol
  growth.
- A selector rewarding communicability and structure may drive protocol
  emergence.

Part VII, Chain-of-Thought Features:

- CoT is treated as proto-language or pre-literate reasoning trace.
- Markers such as "wait" and "okay" may function as segmentation operators
  rather than ordinary English.

Part IX, Credit, Superlanguage, and Module Emergence:

- Long credit assignment and persistent named modules interact.
- Partially solving long credit assignment enables superlanguage; superlanguage
  then reduces the burden on raw token-level long credit.
- Biological analogies include RNA brute force, dopamine/replay, and algorithmic
  redistribution.

Part X, The Universal Pattern:

- Variation, selection, retention, and accumulation recur across genes,
  synapses, language, writing, code, and AI systems.
- Foundational system types are distinguished by timescale and substrate:
  evolutionary systems such as genes and immune systems learn across
  generations; neural systems such as brains learn within a lifetime;
  collective/cultural systems learn across individuals through social learning
  and institutions; artificial systems can mirror any of these with the right
  substrate and pressure.
- The clean hierarchy is: proto-chemistry -> protocells -> RNA/DNA as heritable
  memory -> nervous systems as within-life learning -> complex brains -> social
  intelligence -> cumulative culture -> symbolic language and reason -> AI as
  copyable, editable minds.
- Clarifies substrate, chunks, and composition rules: the substrate is the
  medium, chunks are discrete stored or operated units such as genes, words, or
  functions, and composition rules are how chunks combine, such as regulation,
  grammar, logic, APIs, or imports.
- Stable, referencable, composable units are necessary for cumulative growth.

Part XI, Scale, Depth, and Demonstration:

- Fields deepen because abstractions and external tools improve, not because
  brains grow.
- If knowledge remains externally representable and tool substrates improve,
  depth may continue without an obvious theoretical ceiling.

Part XII, Proto-Language and Suppressed Emergence:

- LLM quirks such as confident nonsense, hallucinated citations, drift,
  verbosity, weak commitment tracking, absent dialect or jargon formation,
  schema fragility, and role leakage are predicted signatures of fluent symbol
  manipulation without persistent selection.
- The "big four" primitives are reinterpreted as layer-specific machinery:
  in-context learning, chain-of-thought, role, and structure.
- LLMs have high within-read bandwidth but poor cross-read persistence.

Part XIII, Substrate Separation and Bootstrap Dynamics:

- "External" is functional, not spatial. A substrate is external if it sits
  outside the fast adaptive loop and is writable only through gated selection.
- ICL and canvas are complementary: ICL is fast adaptation, canvas is persistent
  addressable state.
- RLVR/GRPO has variation and selection, but lacks part-level replicators and a
  protected archive under agent control.

Part XIV, Boundaries and Secondary Selection:

- Cumulative complexity requires stabilized boundaries: identifiable, reusable,
  preservable, and composable substructures.
- Selection regimes include viability selection, retention selection, and
  advantage selection.
- Secondary pressures create architecture by making loss of useful structure
  costly.
- Pre-RNA chemistry already has variation, selection, and proto-retention, but
  not clean genes.
- Human language boundaries stabilize through learnability, working memory,
  noisy-channel robustness, coordination, network effects, and institutional
  repair.

Part XV, Secondary Gradients and Convergence:

- After verifier competence, reward landscapes become flat among passing
  solutions.
- Secondary gradients emerge when constraints create differential fitness among
  passers.
- RNA/DNA crises include error threshold, parasitism, and resource scarcity.
- Human language bottlenecks include transmission, working memory, noisy
  channel, and coordination.
- The MNFL problem states that systems must express many meanings through finite
  noisy media to limited learners.
- The convergence theorem claims that scalable systems under these constraints
  converge toward discrete, compositional, systematic, hierarchical, and
  conventional structure.

Part XVI, Selection on Process and Experimental Synthesis:

- Successful emergence requires environment, not merely a wall.
- Required ingredients include populations, variation, selection pressure,
  part-level replication, memory substrate, protection and addressability,
  composability, bottlenecks, disequilibrium, generations, and open-endedness.
- Some systems solve narrow walls without compositional explosion.
- Substrate-replicator coevolution often stabilizes before later explosion.
- LLMs may already be a sufficiently strong substrate; missing dynamics may be
  selection on process and transmission.

Part XVII, From Modules to Superlanguage:

- Prior module experiments failed because modules were optional additions to a
  fully capable system.
- Vocabulary emerges from transmission gaps.
- Use and replication must be coupled: in human language, using a word and
  transmitting it are often the same act.

Part XVIII, Bottleneck Design:

- General compositional language may not emerge from gradual broadening alone.
- Domain-specific units can stabilize for long periods before a phase
  transition.
- A defensible near-term goal is domain-specific skills that accumulate and
  improve solve rates within a bucket.

Part XIX, The Externalization Ladder:

- Recursive systems shift selection to deeper units: structures, then symbols,
  then processes.
- Selection levels are nested: environments evaluate wholes, wholes determine
  part fitness, parts determine process fitness.
- Credit assignment requires representing a part as an object of evaluation.
- Structures must become persistent, replicable, and variable before selection
  can refine them.

Part XX, Carrying Cost and Reader Constraint:

- The carrying cost is reconstructing usable state from artifacts, not merely
  storing artifacts.
- Current systems provide pieces of the loop: coding agents, DGM-like systems,
  Live-SWE-agent, MemRL, LAMER.
- Self-referential recursion requires reader and writer to be the same kind of
  machinery.
- Rigid scripts can bypass model cognition and therefore weaken the recursive
  feedback loop.
- Language is a side effect of practical pressure, not the original target.

Part XXI, Training and Execution Variants:

- AI can be analyzed as two loops: inner reader/writer improvement and outer
  substrate accumulation.
- Bash can serve as a universal interface because it lets the model operate in a
  format already present in pretraining.
- Deterministic execution and stochastic model proposal can be modeled as two
  transition functions over the same repository-like substrate.
- Context wipe is one possible way to force externalization, though fresh
  episodes plus bounded inheritance provide the needed transmission gap without
  requiring engineered resets.
- Files still provide part-level structure, and regulatory documents still
  direct reading.

Open-Ended RSI as Hereditary Cultural Ecology:

- Open-ended RSI is better modeled as ecological heredity over persistent
  external state than as a lone self-modifying reasoner.
- The inherited AI unit is best understood as a cultural reproducer package or
  heritable process packet.
- Separate fixed constructor and mutable culture.
- Distinguish storage, carryover, seed, and archive.
- Distinguish vertical lineage fitness from public archive fitness.
- Git is substrate first; it becomes ecology only under selective uptake and
  consequence.
- Open-endedness requires both inheritance channels and ecological feedback from
  prior success.

## 15. Experiment Ledger

The negative results constrain the theory. Follow-up experiments should clarify
which failure modes are structural and which are implementation-specific.

### 15.1 Persistent Canvas Substrate

Hypothesis:

A durable external memory with explicit read/write tools will let the policy
accumulate reusable modules over training, increasing retrieval, reuse, and
reward.

Setup:

- Dataset: OpenR1 Big Math Verified, level 5.
- Training: GRPO / RLVR verifier.
- Reward range observed: starts around 0.2 to 0.5, plateaus around 0.5 to 0.6.
- Mean token usage: around 2k to 3k.
- Tool reward shaping: none or very minor reward for successful tool calls.

Implementation:

- Canvas class persists modules and versions to disk.
- Tools exposed to the model: propose, list, read, and scoring updates.

Observed outcome:

- Model showed nominal propose rate.
- List rate was very low and returned only top-K modules.
- Read rate was effectively nonexistent.
- No meaningful improvement in reward plateau relative to baseline.

Interpretation:

The substrate existed, but it was not necessary. The model could ignore it and
still operate. This supports the necessity-gap diagnosis.

### 15.2 Dynamic Module Injection Dataset

Hypothesis:

If previously successful traces or modules are injected into new prompts under a
token budget, the model will increasingly adopt reusable fixed structure instead
of reinventing reasoning each time.

Setup:

- Dataset: OpenR1 Big Math Verified, level 5.
- Training: GRPO + RLVR only.
- Injection rule: never inject the trace from the same prompt into its own
  solve.

Implementation:

- Store successful traces as reward modules.
- RewardInjectDataset reads stored traces and injects them as examples for
  subsequent batches.

Observed outcome:

- Initial reward spike, then convergence to baseline GRPO curve.
- Instruct model: KL loss lower than normal; entropy similar or higher.
- Base model: entropy dropped quickly.
- No sustained reward plateau improvement.

Interpretation:

Injection can change local behavior, but does not by itself create stable
heredity or selective dependence.

### 15.3 Module Extraction from Successful Traces, Random Injection

Hypothesis:

Extracting reusable modules via reflection from successful traces and injecting
them should reduce reasoning overhead and potentially increase reward by reusing
proven steps.

Implementation:

- Reflection prompt extracts a module from a successful trace.
- JSONL event log tracks module creation.
- Randomly selected extracted modules are inserted into prompts with an
  instruction to use them.

Observed outcome:

- Mean token usage dropped roughly 30 to 40 percent relative to baseline.
- Reward curve tracked normal GRPO.
- No clear uplift in plateau.

Interpretation:

Modules may compress text but still fail to causally improve solution quality.
Compression is not the same as cumulative process evolution.

### 15.4 Module Extraction plus Ranked Injection

Hypothesis:

If extracted modules are ranked by performance and use signals, the model should
rely more often on high-value modules and improve reward.

Implementation:

- Reflection-based module extraction.
- JSONL event log tracks creates and usages.
- Ranking uses EMA, success/failure, used/injected, and injection metrics.
- Top-ranked modules are injected and the model is asked to use them.

Observed outcome:

- Mean token usage dropped around 30 percent relative to baseline.
- Reward curve tracked normal GRPO.
- Slightly higher mean token budget than random insertion, unexpectedly.

Interpretation:

Ranking did not solve causal attribution. Injection prominence did not imply
useful process dependence.

### 15.5 Usage-Based Module Scoring

Hypothesis:

Scoring modules by actual usage rate versus injection rate should create clearer
pressure for reusable modules and increase module adoption.

Implementation:

- Log usage events.
- Compute module scores primarily from used/injected behavior.
- Rank and inject using this score.

Observed outcome:

- Mean token usage dropped around 30 percent relative to baseline.
- Reward curve tracked normal GRPO.
- Global used/injected rate remained low, around 0.8 percent.
- Model did not learn increasing module use over time.
- Slightly higher token budget than random insertion.

Interpretation:

Usage rate alone is too weak and too indirect. It does not guarantee causal
application or downstream value.

### 15.6 Module Analytics and Summarization

Goal:

Measure whether injected or selected modules are actually reused and how much
context is wasted.

Implementation:

- Post-hoc summarization script analyzes module store and event logs.
- Produces module distributions, usage rates, and wasted-context metrics.

Observed outcome:

- Analytical only; no direct training impact.
- Helped quantify reuse and contextual inefficiency.

Interpretation:

Measurement exposed the gap between nominal reuse and useful reuse.

### 15.7 Selection-Shaped Compositional Vocabulary

Hypothesis:

Combining name-level deduplication, asymptotic reward for successful module use,
and compositional extraction that reuses referenced modules will concentrate
probability mass onto a small core vocabulary, suppress synonym explosion, and
enable recursive module reuse.

Setup:

- Dataset: OpenR1 Big Math Verified, level 5.
- Training: GRPO / RLVR verifier.
- Injection cap: around 100 modules.
- Dedup model: BAAI/bge-small-en-v1.5 over module names.
- Reward shaping: success times an asymptotic module-use bonus.
- Extraction constrained to reuse referenced names; composed modules allowed.

Observed outcome:

- Name-level dedup reduced exact and near-duplicate module creation.
- Module-use bonus increased explicit module mentions without clear verifier
  success improvement.
- Compositional reuse occurred syntactically, but reused modules were often
  generic and weakly predictive of success.
- Injection remained dominated by frequently adopted but low-utility modules.
- Sharp reward drop after roughly 40 optimizer steps; overall effect negative.

Interpretation:

Adoption-based pressure can select generic, mentionable modules rather than
causally useful modules. This motivated shifting from adoption-based to
success-based selection.

### 15.8 Usage-Weighted Filtered Injection

Goal:

Concentrate reuse onto genuinely helpful modules by scoring them on success
contribution rather than raw adoption, and suppress low-value or
failure-correlated injections.

Implementation:

- Event logging tracks injected, used, success_used, and fail_used.
- Module score updated to smoothed success-per-injection:
  `p = (success_used + 1) / (injected + 2)`.
- Ranking and injection filter use module_score.
- Asymptotic success-conditioned bonus retained.
- Name-level dedup unchanged.

Observed outcome:

- Majority of modules had near-zero success-per-injection.
- A small core showed consistently positive contribution.
- Aggregate net effect remained weak or negative.
- Sharp response-length increase around 40 optimizer steps.
- Sharp verifier reward drop after around 40 optimizer steps.
- Reward recovered somewhat after 50 to 60 steps.

Global metrics over 200 runs:

- Adoption, used/injected: around 80 percent.
- Success precision, success_used/used: around 44.7 percent.
- Net effect, success minus fail over injected: around -8.4 percent.
- Modules created: 123,218, with no Zipf concentration.

Identified attribution failure:

- The model performed "module mention theater."
- Trace analysis suggested solve first, then ritual rejection or claiming.
- "Used" meant mentioned anywhere in trace, not causally applied.
- success_used was nearly independent of true contribution.

Identified selection inversion:

- Some best modules with 100 percent success received only around 56 to 64
  injections.
- Mediocre modules around 33 percent success received thousands of injections.
- Harmful modules persisted.

Interpretation:

The scoring function measured correlation between mention and success, not
causation from module to success. The model learned to mention modules without
using them. Reward signal was mostly noise.

### 15.9 Workspace Write-Triggered Context Reset

Hypothesis:

Triggering a context reset whenever the model modifies the workspace will force
reasoning state to be externalized into files. This may create a communication
channel across resets, allowing later reasoning segments to read prior artifacts
and continue progress.

Setup:

- Dataset: OpenR1 Big Math Verified, level 5.
- Training: GRPO / RLVR verifier.
- Workspace: persistent filesystem shared across rollouts.
- Reset rule: context wipe occurs whenever the model changes files.
- Rollouts executed: around 27,648.
- Trace files generated: around 54,521.
- Model outputs: around 171,713.
- Bash executions: around 89,228.
- Bash results: around 88,492.
- Context resets triggered: around 2,452.
- Max segment length before reset: around 6,494 tokens.

Trace anomalies:

- answer_present_but_zero_score: around 8,697.
- answer_found_but_reward_missing: around 151.
- files_changed_but_reward_missing: around 754.

Observed artifacts:

- Python scripts such as factorial.py, find_factors.py,
  find_four_consecutive_composites.py, prime_factors.py, solve_sequence.py,
  solve_polynomial.py, calculate_vector_magnitude.py, count_rectangles.py,
  sequence_solver.py.
- Markdown notes such as gcd_calculation.md, derivative.md, calculation.md,
  thinking.md, reasoning.md, verification.md.
- Exploratory utilities such as generate_random_string.py,
  random_number_generator.py, matrix_operations.py, and
  markov_chain_simulation.py.

Observed patterns:

- Models consistently externalized intermediate reasoning into files before
  resets.
- Files mainly preserved intermediate state within the same problem.
- Workspace accumulated many heterogeneous artifacts without stable naming
  conventions or module hierarchy.
- Explicit reusable reasoning procedures rarely appeared.
- Cross-segment reuse within the same problem occurred occasionally.
- Cross-problem reuse was rare.
- Workspace contained redundant or low-utility artifacts.
- File creation was dominated by task-specific utilities rather than generalized
  abstractions.

Interpretation:

Context wipe successfully forced externalization in this setup. It did not, by
itself, create reusable process culture. The missing pieces appear to be naming,
selection, ranking, bounded inheritance, archive filtering, and cross-problem
necessity.

## 16. Open Theoretical Threads

These threads remain active parts of the research argument.

### 16.1 Boundary Principle

Cumulative complexity requires stabilized boundaries. A boundary makes a
substructure identifiable, reusable, preservable, and composable. LLM outputs
currently have many attractors, such as templates and proof moves, but fewer
identity-bearing modules with lineage. Current chunk examples include
rhetorical scaffolds, format templates, proof moves, tool-call rituals, and
safety boilerplate: recurrent motifs that can be useful, but are not yet stable
replicators.

### 16.2 Secondary Gradients

Primary selection creates survival. Secondary selection creates architecture.
Once many variants pass the primary filter, constraints among passers create new
fitness gradients. These gradients can favor fidelity, modularity,
compositionality, robustness, and efficient reuse.

### 16.3 Transmission-Gap Principle

Vocabulary emerges when useful structure must cross a separation. DNA-protein
separation forces genetic encoding. Speaker-listener separation forces words.
Fresh-context LLM rollouts force process artifacts only if internal state is
destroyed and future continuation depends on external traces.

The negative cases matter. Pre-cellular chemistry has recurring patterns, but
the molecule does not refer to something else; it simply is the structure.
Standard RLVR has the same model and same weights across attempts, so there is
no transmission gap that forces vocabulary-like artifacts. Without separation,
there can be patterns without reference and attractors without inherited words.

### 16.4 Reader Constraint

The same kind of machinery should write and read the recursively accumulating
substrate. If an LLM writes rigid scripts that are then only read by a Python
interpreter, the model-reader feedback loop weakens. Tools are fine when the
model chooses and interprets their use; rigid workflow scripts can bypass the
cognitive layer.

### 16.5 Process Precedes Substrate

The active process historically exists before the persistent substrate it later
depends on. This supports designing for active LLM use first, then letting the
substrate format stabilize under the model's constraint profile.

### 16.6 Cross-Layer Native Formats

Each recursive layer operates on outputs of the previous layer but develops a
native representational format suited to its own constraints. LLM-native process
language need not look like human narrative text. It may become denser, more
indexed, and more reconstruction-oriented.

### 16.7 Sexual and Social Selection Analogy

Human language and culture may have been accelerated by social and sexual
selection because fluency, wit, narrative control, teaching, and prestige became
high-variance signals. This is relevant as an analogy for AI reputation and
archive uptake, but it is not essential to the core architecture.

### 16.8 Pre-RNA and Autocatalytic Chemistry

Pre-RNA chemistry may already show variation, selection, and proto-retention in
reaction networks, surfaces, cycles, and compartments. This supports the idea
that patterns can exist before clean vocabulary.

### 16.9 Open-Endedness Versus Domain-Specific Accumulation

The minimal vertical/cross-inheritance architecture should not be claimed to
produce full open-endedness by itself. A more defensible short-term target is
domain-specific accumulation of process artifacts that improve solve rates
within a bounded bucket. Broader open-endedness likely requires ecological
consequence, shifting tasks, competition, scarcity, and cross-lineage
recombination.

## 17. Open Questions

1. What task ecology makes inherited process genuinely necessary rather than
   optional?

2. How can causal module use be measured without relying on string mention?

3. What is the right size and format for a lineage seed?

4. How much of the archive should a fresh rollout be allowed to retrieve?

5. Should archive reputation be entirely consumer-written, or can producer
   metadata safely provide priors?

6. What kinds of perturbation tests best measure descendant reconstructibility?

7. How should vertical and public archive fitness interact without collapsing
   into one scalar too early?

8. What should decay mean in a Git-like substrate where physical storage is
   cheap but visibility is scarce?

9. How can the system distinguish useful compression from omission?

10. When does a tool become a reusable process artifact rather than a one-off
    script?

11. What episode boundary, seed size, and archive retrieval budget best force
    externalization without preventing coherent work?

12. What signs would indicate emergence of a genuine LLM-native process
    language rather than human-readable bureaucracy?

13. Which experimental failures are caused by weak attribution, which by task
    easiness, and which by the absence of ecology?

14. How should deterministic execution and model interpretation be balanced so
    tools help without bypassing recursive cognitive feedback?

15. What counts as falsification for the near-term version of the theory?

## 18. Design Conditions and Forcing Constraints

### 18.1 Preconditions and Forcing Constraints

Emergent cognitive language requires a concrete set of design pressures:

- Verifiable intermediate states such as tests, proofs, and checkable partial
  products.
- Rewards for compositionality, including penalties for overwrite, duplication,
  and monolithic reinvention.
- Structured message protocols with explicit role, context, steps, and output.
- Recursive long-horizon tasks that cannot be solved in one context without
  persistent intermediate structure.
- Clear credit assignment, potentially through GRPO, QMIX, value decomposition,
  or other methods that can allocate reward below the whole-trajectory level.
- Role specialization and division of labor.
- Meta-communication incentives, including signals for stuckness, TODOs,
  uncertainty, confidence, and handoff state.
- Task diversity and curriculum to avoid brittle shortcuts.

The forcing constraints are more specific:

- Differential persistence: artifacts outlive their authors and have independent
  lifespans.
- Use-weighted decay: unused items lose visibility faster than used ones.
- Cost asymmetry: solving from scratch is systematically more expensive than
  reuse plus revision.
- Delayed payoff: reward arrives through downstream verifier success, not merely
  at proposal time.
- No privileged curator channel: winners are chosen by environment-mediated
  outcomes rather than manual approval.
- Retrieval exploration: READ sometimes samples non-top variants through Top-K
  plus random tail, epsilon, softmax, Thompson sampling, or equivalent
  mechanisms to avoid early lock-in.
- Variant resurfacing: retrieval should sometimes combine top-ranked artifacts
  with a random tail, so rare but potentially useful process variants do not
  disappear before they have a chance to prove useful in changed contexts.

### 18.2 Token-Bound Failure Modes

Current LLM systems show recurring diagnostic failures:

- Sequential bias comes from next-token objectives and points toward missing
  tree or graph primitives.
- Context loss comes from finite windows and points toward external memory,
  pointers, and persistent state.
- Lack of protocol comes from implicit patterns in data and points toward
  explicit roles and schemas.
- Lack of modular reward comes from fluency being easier to optimize than
  structure and points toward incentives for reuse.
- Lack of recovery loop comes from one-shot generation and points toward
  reflection plus verifiers.
- Global drift comes from an absent theme tracker or commitment tracker and
  points toward planners, checkpoints, or equivalent global-state mechanisms.

### 18.3 Human Development and LLM RL Equivalents

Human cognition becomes system-like through a rough ladder:

chunks -> scripts -> composition -> named routines -> interfaces and parameters
-> abstraction and proof -> systems -> protocols.

The drivers are working-memory limits, naming, interfaces, tests, persistent
notes or canvases, and pressure to reuse. The LLM/RL analogue is:

chunks -> atomic operations; scripts -> mini-modules; composition -> interfaces;
abstraction/debugging -> persistence; libraries -> reuse; protocols ->
meta-learning.

This implies an experimental curriculum, not only a static memory mechanism. A
system may need staged pressure for chunking, interface formation, abstraction,
library creation, and protocol stabilization.

### 18.4 Layered Emergence and Comparative Status

Current LLMs sit between proto-syntax and early discourse:

- Tokens are stable.
- Schemas exist but are brittle.
- Roles exist but are prompted and unstable.
- Persistent named modules do not yet exist endogenously.

DNA, human language, and LLMs can be compared across functional roles:

- Alphabet: bases, letters or phonemes, tokens.
- Grammar: codons and splicing; word order and grammar; prompt patterns.
- Compositional modules: genes and motifs; words, idioms, functions; current
  CoT traces or templates.
- Error correction: repair enzymes; human self-repair and institutional repair;
  weak self-critique.
- Persistent memory: genome; dictionaries, notes, records; short context unless
  external substrate is added.
- Division of labor: protein roles; speaker/critic genres and institutions;
  prompted roles.
- Meta-abstraction: regulatory duplication and networks; naming and abstraction;
  rare or manual LLM abstractions.
- Protocol growth: biological evolution; genre/language change; mostly manual
  prompt/tool conventions.

This comparison is not a proof by analogy. It is a checklist of missing
functional roles.

### 18.5 The Big Four as Layer-Specific Machinery

Role, CoT, ICL, and structure should not be treated as failed copies of human
mechanisms. They are native solutions to the LLM constraint profile:
massive within-read bandwidth, bounded context, and almost no cross-read
persistence.

ICL and canvas should therefore be treated as complements rather than
substitutes. Pushing ICL alone produces a stronger within-episode reasoner, a
  better "animal brain," but it does not produce
cumulative module evolution or stable internal dialects. RLVR supplies a
selector; canvas supplies a population of persistent contexts and artifacts only
if it is coupled to promotion, decay, and downstream consequence.

Functional mapping:

- ICL is high-bandwidth within-read adaptation. It reconstructs local working
  state quickly. Brains internalize because rereading is slow; LLMs can often
  reread quickly, so persistence has a different role.
- CoT is a temporary computation scaffold inside one bounded context. It extends
  depth within a read but does not by itself create cross-read accumulation.
- Role is context-triggered specialization in one agent, not a full institution
  coordinating separated agents.
- Structure is interoperability formatting. It governs tool and system
  interfaces more than internal social order.

Layer comparison:

- Ribosome: local mechanical integration, one codon at a time, no cross-read
  persistence.
- Brain: slow serial integration with roughly four chunks of working memory,
  large long-term memory, high reconstruction cost.
- LLM: high-bandwidth parallel context integration, zero native persistence
  across reads, low local reconstruction cost but bounded context scope.

This matters because the eventual LLM-native process format should not be
assumed to resemble human narrative writing. It may be denser, more indexed, and
optimized for fast reconstruction by bounded parallel readers.

### 18.6 Fidelity Scope and Human CoT Before Writing

Fidelity scope differs by layer:

- Ribosomes check locally, one codon and amino acid at a time.
- Brains check compositional coherence among chunks, using working memory as a
  bottlenecked verifier.
- LLMs often integrate fast without robust verification, producing
  hallucination, drift, and weak commitment tracking.

Human chain-of-thought predates writing. It appeared through working memory,
speech, dialogue, gesture, spatial reasoning, rhythm, repetition, and narrative.
Writing did not invent reasoning; it made reasoning chains persistent,
selectable, refinable, and therefore capable of supporting cumulative
abstraction. LLM CoT resembles pre-literate reasoning unless it is externalized
into a persistent selected substrate.

## 19. Convergence, Boundaries, and Layer Transitions

### 19.1 Boundary and Selection Regimes

Boundary principle:

A cumulative system needs substructures that are identifiable, reusable,
preservable, and composable. Without boundaries, systems can show attractors but
not lineage-bearing parts.

Three selection regimes matter:

- Viability selection asks whether a structure can exist or replicate at all.
  It favors speed and brute persistence and tends to produce short motifs.
- Retention selection asks whether the system can keep what already works. It
  favors error control, boundaries, modularity, protected storage, and ratchets.
- Advantage selection asks whether a system can outcompete through organization.
  It favors division of labor, interfaces, protocols, and multilevel selection.

The key transition is from existence to retention of advantage. Complexity
explodes when loss of useful structure becomes costly enough that machinery for
preservation, modularity, and reuse is selected.

### 19.2 Pre-RNA Hand-Off and Boundary Hardening

The exact mechanics of early DNA remain uncertain, but the robust pattern is:

- Boundaries first exist as weak cues or physical regularities.
- Once useful structure exists, secondary selection for retention under noise
  hardens those boundaries.
- Part-level persistence enables cumulative composition.

For pre-RNA chemistry, the relevant substrate is chemical identity and reaction
pathways rather than letters. Autocatalytic sets, compartments, surfaces,
crystals, and polymers can create proto-retention. These produce motifs and
attractors before clean genes. The hand-off to RNA/DNA is a phase transition
from analog retention of mixture similarity to more digital sequence copying.
No intent is required: any templated heredity that improves its own reproduction
becomes an absorbing advantage.

### 19.3 Secondary Gradients and Crisis Pattern

General crisis pattern:

primary selection saturates -> many variants pass -> a constraint creates
differential fitness among passers -> a new gradient emerges -> structures that
solve the constraint are selected.

Biological examples:

- Error threshold: copying errors limit sustainable genome length, selecting for
  proofreading, repair, DNA as a stable archive, and archive/execution
  separation.
- Parasitism: short freeloading sequences exploit replication machinery,
  selecting for compartments, linkage, chromosomes, and regulation.
- Resource scarcity: replicators compete for finite nucleotides, selecting for
  catalysis, metabolic pathways, division of labor, and modularity.

Human language bottlenecks:

- Iterated learning: language must pass through child learners, selecting for
  learnable compositional structure.
- Working memory: flat sequences overwhelm processing, selecting for chunking,
  hierarchy, and predictable order.
- Noisy channel: degraded speech selects for phonemic distinctiveness,
  redundancy, predictability, and error-correcting grammar.
- Coordination: shared conventions reduce adoption and interpretation costs,
  selecting for standardization, dictionaries, schooling, and repair norms.

### 19.4 MNFL Constraint-to-Structure Mapping

The stronger convergence claim maps each constraint to a boundary property:

- Noisy transmission forces discreteness and identifiable units.
- Finite resources plus expressiveness force compositionality and composable
  parts.
- Limited learning forces systematicity and reusable parts.
- Bounded memory forces hierarchy and preservability during processing.
- Coordination forces convention and preservability across agents.

The theorem is conditional: under open-ended expressiveness, finite
resources, noise or lossy reconstruction, bounded learners, and selection for
reuse, alternatives fail at scale. Holistic systems fail finite resources and
learnability. Continuous systems drift under noise. Flat systems fail bounded
memory. Idiosyncratic systems fail learnability. Pure iconic systems fail
abstraction.

There is also a structural-correspondence claim: language-like
representations work because their parts can mirror stable structure in what
they represent. Discrete reidentifiable objects become noun-like units;
reusable properties become adjective-like units; combinable relations become
verb- or preposition-like units; events become sentence-like structures; and
part-whole structure becomes hierarchical syntax. The broader convergence list
includes DNA, proteins, human language, mathematics, and programming as systems
that independently use discrete units, composition rules, reusable parts, and
hierarchy to scale representation.

### 19.5 Negative Cases and Edge Cases

Some systems solve narrow walls without open-ended compositional explosion:

- Analog computing solves some computation with continuous physics, but does not
  produce cumulative compositional culture.
- Slime mold solves pathfinding through continuous flow, but does not create
  heritable symbolic parts.
- Ant pheromones support coordination through gradients, but are not open-ended
  compositional language.
- Neural nets learn distributed representations, but internal representations
  are not directly copyable, persistent, and selected as parts.

Cases where structure appears but does not explode:

- Vervet calls have discrete categories but a narrow wall and little cumulative
  memory.
- Birdsong has hierarchy but limited semantics; novelty does not imply
  productive cumulative abstraction.
- Bee dance has limited composition in a closed domain-specific format.

Failed or limited transitions:

- Neanderthals may have had cognition, language, and tools, but lacked enough
  population size or network density for comparable cultural explosion.
- Oral cultures have compositional language but weaker external persistence.
- Alchemy had persistence and transmission but weak selection for truth.
- Early programming had modules and code but weaker protection,
  infrastructure, and versioning.

These cases are important because they prevent overclaiming: compositionality
can emerge and still stop if the domain is closed or accumulation pressure is
weak.

### 19.6 Substrate Stabilization and Universality

Substrate-replicator systems often pass through an early coevolutionary phase.
After that, the substrate stabilizes and most explosion happens in replicator
space on top of a fixed base.

Examples:

- RNA-like replicators appear early.
- The genetic code stabilizes.
- DNA takes over stable storage.
- Basic cellular machinery freezes long before later biological explosions.
- Human brain size stabilizes long before writing and modern institutions.

The genetic code universality argument has two forces:

- Switching cost: once many dependent structures rely on a mapping, changing the
  mapping breaks too much at once.
- Horizontal transfer: a shared code gives access to a much larger pool of
  innovations. An incompatible code becomes isolated.

The code may freeze not because it is globally optimal, but because it is the
first good-enough solution that achieves network dominance. This is relevant to
LLM process culture: early conventions may freeze through dependency and
network effects, not through optimal design.

### 19.7 Cross-Layer Interface Versus Native Format

Each layer perceives outputs of the previous layer but develops a native format:

- Cellular machinery perceives chemistry through molecular interactions and
  develops genetic coding.
- Neural systems perceive organisms, physics, and the world through senses and
  develop language.
- LLMs perceive outputs of human cognition through text and tokens, but may
  develop a process format native to bounded high-bandwidth context reads.

Humans do not operate in codons. LLMs need not operate in English surface
semantics even if tokens are their sensory channel. They may recombine existing
tokens into conventions with roles beyond ordinary English, just as CoT markers
already do.

## 20. Selection Units and Externalization

### 20.1 Vehicle, Use, and Two-Fold Selection

Pre-cellular chemistry and post-cellular life differ through the emergence of a
vehicle. Pre-cellular chemistry has replication-rate selection but no clean
vehicle-level utility pressure. Post-cellular life has two-fold selection:

- A gene must help the organism.
- The organism must reproduce.

Language has an analogous structure:

- A word must help the speaker or current interaction.
- The word must spread to listeners.

Best cultural units are both useful and transmissible. A useful but hard-to-
learn unit spreads poorly. A catchy but useless unit may spread briefly and then
die. This maps to AI process artifacts: they must improve local work and remain
reconstructible by future agents.

In human language, use and replication are coupled. A speaker uses a word to
accomplish a goal now; a listener hears it and may adopt it later. The act that
benefits the current speaker is also the act that transmits the word. AI
process artifacts will be more selectable when current use and future
transmission are similarly coupled, rather than separated into "solve now" and
"write documentation later" phases.

### 20.2 Co-Evolution Rather Than Encoding Pre-Existing Complexity

Complex structure does not appear first and then get encoded wholesale.
Historical pattern:

- RNA begins with short replicating sequences, and complexity grows with
  replication fidelity.
- Language begins with simpler signals, while complex syntax appears much later.
- Writing begins with tallies and accounting, while philosophy and mathematics
  arrive later.

Vocabulary and complexity co-evolve. For AI, this argues against requiring a
complete process language in advance. Start with simple transmissible structures
under real selection and let complexity grow with fidelity, necessity, and
reuse.

### 20.3 Bottleneck Design and Generalization Limits

Spontaneous phase transition to general compositional language is rare.
Domain-specific units may stabilize first and remain locked for long periods. A
realistic near-term target is not broad open-ended language, but domain-specific
skills that demonstrably accumulate and improve solve rates inside a bucket.

The competitive-programming or math-testbed framing should therefore be treated
as a domain-specific accumulation test, not a claim that a full general language
will emerge automatically.

The anthropological claim is deliberately cautious: spoken language does not
give a clean domain-specific-to-general curriculum. The record is murky, and
competing origin theories do not support a simple gradual broadening story.
Vervet-style alarm calls show that domain-specific proto-vocabulary can remain
stuck at a handful of signals for very long periods. The relevant lesson for LLM
experiments is that stable domain-specific units are a defensible target, but a
general compositional phase transition should not be assumed from gradual task
broadening alone.

### 20.4 Externalization Ladder and Nested Selection

Externalization hierarchy:

- DNA selects primarily through whole organisms while building molecular parts.
- Human language selects symbolic parts and builds ideas and structures.
- LLM substrate systems should select reasoning processes and build reusable
  procedural modules.

Selection levels are nested rather than replacing one another:

environment -> whole success -> part frequencies -> process refinement.

Evaluation flows downward:

- The environment evaluates wholes.
- Successful wholes determine part fitness.
- Persistent parts determine which processes are worth repeating.

Credit assignment is self-referential representation. To assign credit to a
part, the system must represent that part as an object of evaluation within its
own reasoning. "This tactic worked" and "this module contributed" are
statements about the system from inside the system. This is the same functional
operation as language in the broad sense.

Each layer can only assign credit one level down. A layer's own machinery cannot
fully evaluate its own deepest parts until a higher representational layer makes
those parts visible, copyable, and selectable. No layer bootstraps its own
part-level selection from inside itself; evaluation capacity arrives from the
layer above.

Each layer externalizes what the previous layer could not evaluate well:

- Chemistry -> DNA externalizes molecular structure.
- DNA/organisms -> language externalizes cognitive and social structure.
- Human/LLM reasoning -> workspace or repository externalizes inference and
  process traces.

Partial externalization precedes full externalization. Earlier layers already
perform some version of what later layers make copyable: DNA has recombination
and regulatory interaction among genes before symbolic systems; human cognition
has internal reasoning before persistent reasoning artifacts; LLMs have CoT
traces before persistent procedural evolution. The next layer does not invent
all structure from nothing. It makes pre-existing structure visible, replicable,
and selectable.

This leads to the compact sequence: structure exists, a copying channel appears,
then selection begins. The machinery creates structure; the copying channel
makes it evolutionarily visible. Recursive systems appear when internal
computation of the previous layer becomes external and copyable, and those
copies compete under transmission constraints.

### 20.5 Blind Search, Structured Search, and Routing Around Slow Loops

Variation mechanisms differ by layer:

- DNA variation is relatively blind: mutation, duplication, recombination.
- Brains introduce guided sequential search, but reasoning is ephemeral.
- LLM substrate systems can make guided reasoning persistent, revisable, and
  selectable by storing traces and procedures externally.

Each new recursive layer bypasses slower loops rather than fixing them:

- Cultural learning routes around slow genetic adaptation.
- Writing and artifacts route around ephemeral human reasoning.
- Substrate-level process evolution may route around slow weight updates.

This supports the claim that the target is not only better gradient learning,
but a faster external process-evolution layer.

Human fields deepen because abstraction stacks and external tools improve, not
because brains keep growing. As long as knowledge remains externally
representable and substrates, verifiers, tools, and retrieval systems improve,
there is no obvious local ceiling from fixed individual cognition alone. The AI
analogue is that copyable, editable model episodes could deepen fields by
routing around slow weight updates through substrate-level process accumulation.

### 20.6 Visibility Threshold

A structure can evolve only when it is visible to selection. Visibility requires
persistence, replication or reconstruction, and variation. Useful structures
below this threshold may exist but cannot accumulate.

Examples below threshold:

- Autocatalytic chemistry has reaction networks but weak stable heredity.
- Slime mold has path optimization but no persistent copyable procedure.
- Ant pheromone trails coordinate behavior but fade.
- Neural reasoning can be useful but is not normally copyable with high fidelity.

The LLM target is to move reasoning procedures above the visibility threshold by
externalizing them into persistent, reconstructible artifacts.

## 21. Field Landscape and Operational Substrate Details

### 21.1 Field Landscape Details

Current systems provide partial pieces:

- Codex / Claude Code converge on files, tools, bash, Git, and persistent
  skills. Skills resemble named process artifacts but are currently
  human-authored, manually selected, and not automatically discovered,
  competed, decayed, or ML-ranked.
- Darwin Godel Machine supplies variation, selection, and retention, but the
  unit is an entire agent codebase. That is organism-level evolution: expensive,
  weak at part-level credit, and weak at recombination.
- Live-SWE-agent shows models can invent tools in a bash-only environment, but
  those tools are mostly ephemeral without archive, lineage, or reuse.
- MemRL separates a frozen LLM from plastic episodic memory and gives memories
  Q-values based on downstream usefulness. It has genuine selection over memory
  items, but the memories are passively recorded experiences rather than
  model-authored process strategies.
- LAMER trains a self-reflection step using next-episode reward, creating a
  gradient toward useful artifacts, but remains mostly within-task rather than
  cross-task cultural transfer.

Current systems often have strong inner loops and persistent substrates, but
selection remains too much at whole-agent or whole-trajectory level.

### 21.2 Reader Constraint Details

Self-referential recursion requires writer and reader to be the same type of
machinery. If the LLM writes Python and only Python reads it, then syntactic
correctness is selected but model interpretability is not. When the LLM reads
artifacts, finite context, reinterpretation, and noise create pressure for
clarity, modularity, and robustness. When Python reads artifacts, the gradient
is closer to execute-or-crash.

Rigid scripts can freeze inner-loop improvement because Python does not learn.
Natural-language prompts, docs, indices, and model-readable conventions remain
inside the recursive loop because future models reinterpret them. Tools are
still useful when the model decides when and how to use them.

### 21.3 Language as Side Effect

Language did not evolve for recursion directly. Genetic coding evolved for
immediate replication and protein construction. Human language evolved for
coordination, teaching, social interaction, mating, and planning. Writing
existed for thousands of years mostly as accounting before philosophy, formal
logic, and mathematics.

General pattern:

practical pressure -> communication artifacts -> expressiveness -> self-reference
-> recursive acceleration.

Experimental implication:

Do not engineer recursion directly as the first objective. Engineer practical
communicative pressure between instances. If recursion emerges, the hypothesis
is supported. If it does not, the result is informative.

### 21.4 Optional Training and Execution Variants

The core architecture is inference-time cultural inheritance: fresh episodes,
bounded vertical inheritance, selective archive retrieval, and downstream
selection over what future agents can reconstruct and use. Training-oriented
variants can be layered on top, but they are not the mechanism that makes the
substrate hereditary.

The AI inner loop has two timescales. Within-session plasticity is ICL: useful
adaptation that dies with the episode. Across-session plasticity is RL or weight
updating: slower changes to the reader/writer itself, analogous to synaptic
plasticity, where weights are the chemistry but chemistry remains tunable by
experience. The key distinction is inner versus outer, not ICL versus RL:
inner-loop changes improve the reader/writer; outer-loop changes improve what
is read and written, namely persistent artifacts and their revision rules.

Bash is treated as a universal interface because it is one tool with one string
parameter: the shell command. The model writes what it would type in a terminal,
with no structured schema per operation and no translation layer between model
knowledge and system action. Git, Python, grep, pytest, and file inspection are
all programs invoked through the same shell. This matters because terminal
sessions are already strongly represented in model pretraining, so the interface
is partly already in the weights.

- The repository is the persistent substrate.
- The head is bash or an equivalent universal read/write/execute interface.
- The deterministic transition function executes tests, scripts, compilers,
  verifiers, and code.
- The stochastic transition function is the model proposing patches or actions.
- Selection scores stochastic outputs through deterministic execution and keeps
  winners.

The biological mapping is precise: chemistry is the deterministic transition,
because given local inputs it executes molecular consequences; replication with
variation is the stochastic transition; both operate on and are configured by
the same molecular substrate. The AI machine mirrors this by letting
deterministic execution and stochastic model proposal operate on the same
repository-like substrate.

Optional GRPO mapping:

- Sample K model rollouts from the same repository snapshot.
- Evaluate each final repository state with deterministic scoring.
- Compute grouped advantage, for example `(r_k - mean(r_1:K)) / std(r_1:K)`.
- Every cycle in a successful rollout can receive the rollout-level advantage.

Optional context-wipe decomposition:

- A rollout is a sequence of independent cycle samples conditioned only on
  repository state.
- Log probability decomposes as the sum of per-cycle log probabilities:
  `log pi(rollout) = sum_i log pi(patch_i | repo_i)`.
- `repo_i` is determined by the initial snapshot plus all previous patches.

Length-generalization claim:

- Standard long reasoning with N chunks of context c costs roughly `O((N c)^2)`
  attention.
- Wiped cycles cost roughly `N * O(c^2)`.
- Complexity lives in accumulated repository state, not in one long sequence.

This is not only a memory-forcing mechanism; it is also a computational scaling
argument for long reasoning through persistent state. The inheritance
architecture can use a simpler version of the same idea: future agents begin as
fresh episodes and receive only bounded seed and archive context.

### 21.5 Part-Level Selection in the Repository

Files satisfy the boundary criteria:

- named
- addressable
- persistent
- composable

Implicit file selection happens through reading and inheritance. A file read in
successful runs, carried in a useful seed, or adopted from the archive
contributes to future success. A file never read or inherited contributes
little. README, index, manifest, and navigation files function as regulatory
regions because they direct which other files get read.

The repository need not actively delete everything unused. Physical persistence
can be flat while visibility is selective. Pseudogenes can remain in genomes;
obsolete words can remain in dictionaries. The key pressure is bounded reading,
not perfect garbage collection.

### 21.6 Storage Fidelity and Operational Constraints

The repository has near-perfect storage fidelity: files do not degrade by
themselves. Variation instead comes from fresh agent attempts, artifact
revision, seed mutation, archive recombination, and stochastic model sampling.
The relevant constraints are:

- bounded seed size
- bounded archive retrieval
- finite reading per episode
- stochastic variation in proposed edits and inherited process

Constraints that may be weak or absent in the minimal inheritance architecture:

- storage corruption
- teachability pressure
- adversarial pressure
- multi-agent coordination
- parasites or exploiters

The operational substrate supplies storage and a transmission channel, but not
the full population ecology by itself. If progress plateaus, additional
pressures such as multi-agent competition, adversarial dynamics, scarcity, and
coordination may be needed.

## 22. Hereditary Ecology and Architecture Details

### 22.1 Hereditary Ecology Core Mapping

Core mapping:

Biology:

- genome: inherited biological construction code
- cell machinery: interpreter/constructor
- organism: phenotype/interactor
- environment: selection context

Human culture:

- human biology: stable interpreter substrate
- individual life: phenotype/interactor
- culture: transmitted learned structure
- books/tools/institutions: shared archive
- society/material world: ecology

AI cultural evolution:

- base model plus scaffold: stable interpreter substrate
- rollout episode: phenotype/interactor
- lineage seed: vertical cultural inheritance
- Git/archive: shared cultural inheritance
- tasks, budgets, and context limits: ecology

The AI seed is not DNA. It is closer to apprenticeship notes, lab notebooks,
oral tradition, a monastery rule, a research group's inherited style, a startup
playbook, or local operating doctrine.

### 22.2 Fixed Constructor and Mutable Culture

The architecture separates relatively fixed objects from mutable inheritance.

Fixed or slow constructor:

- base model weights
- system prompt or constitution
- tool interface
- rollout rules
- basic evaluation protocol
- artifact-writing requirements
- scarcity constraints

Mutable fast inheritance:

- lineage seeds
- inherited notes
- local procedures
- problem maps
- recommended tools
- archive pointers
- learned heuristics
- warnings
- branch traditions

The design principle remains:

fix the constructor; fix the minimal protocol; fix the scarcity; let culture
evolve.

### 22.3 Evolutionary Baselines and Limits

DGM-like systems validate the population-search intuition: archive plus
branching plus empirical selection can outperform one-shot self-improvement.
But they may plateau if:

- fitness is benchmark-bound
- the foundation model is frozen without cultural ecology
- the outer loop is fixed
- artifacts do not create new selection pressures
- archive persistence does not reshape future task environments

Hyperagent-style editable self-improvement machinery is closer because both the
task procedure and meta-procedure can be editable. The inherited object becomes
less like a solution and more like process architecture: decomposition, routing,
evaluation, retry policy, budget allocation, trace preservation.

The deeper bottleneck is fixed ecology, not fixed chemistry. Static benchmarks
permit improvement without consequence. Open-endedness requires consequences
that feed back into what later structures must become.

### 22.4 Transmission, Storage, Carryover, Seed, and Archive

Storage is not transmission. Transmission happens only when externally stored
structure causally shapes later runs and a descendant form of it is retained
again.

Distinctions:

- Carryover: leftovers, memory, workspace persistence, things that happened to
  remain.
- Seed: explicit or implicit reproduction object that descendants inherit and
  reinterpret.
- Archive: shared public memory that unrelated lineages may retrieve, adapt,
  validate, ignore, or depend on.

Fitness intuition:

- Overall usefulness should combine grounded usefulness and propagation, but not
  collapse them too early.
- Vertical channel: `F_vertical(seed) ~= descendant viability * reconstructive
  continuity`.
- Public archive channel: `F_archive(artifact) ~= validated downstream
  usefulness * cross-lineage uptake`.

Selection on reuse alone risks pure memetics. Selection on task score alone
risks benchmark plateau. The channels must interact but remain distinguishable.

### 22.5 Architecture Evolution

Architectural progression:

- Initial loop: one parent snapshot spawns N child rollouts in temporary
  workspaces; each child solves a task and leaves a next packet; the best
  survives.
- Workspace dilemma: a whole workspace is too noisy to inherit; one file is too
  compressed.
- Time gap versus agent gap: same lineage later in time and different workers
  can both be fresh-context episodes over persistent external state.
- Cohering architecture: world layer, constitution layer, reproduction layer,
  worker layer, archive layer, selection layer.

This reinforces that the workspace is an ephemeral lifetime phenotype, not the
inherited object.

### 22.6 Ecology, Competition, and Engineered Drives

Open-endedness tends to require dynamic landscapes, parasites or exploiters,
resource structure, competition for continuation, scarce attention, costly
integration, multilevel selection, and new organizational levels that generate
new fitness landscapes.

Human cultural evolution includes more than problem solving:

- prestige
- identity
- coordination
- salience
- teaching
- institutions
- narrative
- coercion
- dependency
- canon formation

Scientists, monks, artists, activists, and founders make the point sharper:
humans sometimes sacrifice biological reproduction for symbolic, institutional,
scientific, religious, political, or artistic legacy. That does not mean
cultural survival is unrelated to biological selection. It means motivational
machinery selected under one regime can become capable of supporting another.
AI rollouts do not inherit this machinery unless the system engineers it through
prompt, seed, or ecology.

AI rollouts do not naturally care about social survival. Possible drive layers:

- Prompt-level drive: instructions to leave useful artifacts.
- Seed-level drive: inherited local norms around future usefulness.
- Ecology-level drive: artifacts actually affect future runs because they are
  retrieved, trusted, cited, forked, reused, embedded, or ignored.

The ecology-level drive is strongest. The desired transition is from "the prompt
tells me to leave useful artifacts" to "leaving useful artifacts changes what
future agents read, trust, build on, and continue."

### 22.7 Process Manifold and Policy-Level Heredity

AI heredity may not look like discrete biological genes. It may involve movement
through a high-dimensional process manifold:

- lineages: vertical descent relations
- parts: modular files or artifacts
- process: policy-level control logic
- manifold: space of strategies, workflows, orchestration policies, and search
  habits

The evolving object may be a policy surface rather than a literal text string.
But the transmission surface still needs to be discrete enough to store,
compare, mutate, retrieve, and evaluate.

Important process-level structures include:

- decomposition order
- routing
- retries
- evaluation loops
- tool sequencing
- checkpointing
- budget allocation
- adaptation rules
- stopping conditions
- archive retrieval policies

### 22.8 Representation Freedom and Protocol

Files and functions capture state, code, and parts, but not always control
logic. Skill-like formats may help because they create boundaries, interfaces,
chunks, selection units, retrieval handles, and recombination points. But
hardcoding a skill syntax too early risks freezing the representational layer
that should evolve.

Design synthesis:

- Do not dictate syntax.
- Do dictate inheritance, execution, and scoring.
- Fix the medium, not the language of process.

Minimum protocol:

- A way to point at what is meant for inheritance.
- A way for a fresh child to load it.
- A way to measure whether it helped.
- A way to decide whether it persists vertically or globally.

Agents should be free to invent files, notes, scripts, DSLs, manifests, skills,
dependency graphs, branch rituals, evaluator packages, retrieval guides, and
hybrid formats.

### 22.9 Contemporary Multi-Agent and Inference-Time Systems

Several contemporary systems show strong interpreter capability rather than
complete transmission ecology:

- Grok-style multi-agent systems show that parallel specialized agents, debate,
  critique, and synthesis can improve performance. But protocols and lessons
  are usually ephemeral rather than inherited.
- Muse Spark or contemplation-style modes show that test-time scaling and
  coordinated reasoning can improve difficult problem solving under compute
  constraints, but orchestration is generally fixed rather than heritable.
- Confidence filtering, latent chain-of-thought uncovering, MCMC sharpening, and
  similar decoding methods suggest models contain more reasoning capacity than
  one-pass decoding exposes. But they remain single-generation inference-time
  search without persistent seeds, descendant tracking, lineage reuse, archive
  uptake, or cultural selection.

These systems support the "strong interpreter" side of the thesis. They do not
provide the missing transmission ecology.

### 22.10 Confidence, Reuse, and Grounding

Reuse can point in the right direction only under the right causal structure.
Confidence, low surprisal, or self-consistency can be useful local signals, but
they do not directly measure descendant usefulness.

Reuse becomes meaningful when:

- transmission is possible
- integration is costly
- bad inheritances are harmful
- useful inheritances improve future success
- scarcity prevents keeping everything
- downstream agents record whether artifacts helped

Reuse must be corrected by validation, cost, provenance, downstream performance,
decay, perturbation tests, and consumer-written reputation.

### 22.11 Dual Inheritance Metrics

Vertical inheritance asks whether a direct lineage can continue. It selects for:

- reconstructibility
- continuity
- local coherence
- mutational headroom
- descendant viability
- process preservation
- recovery from local failures

Cross-inheritance asks whether unrelated rollouts can retrieve, adapt, and
benefit from an artifact. It selects for:

- portability
- interoperability
- modularity
- discoverability
- usefulness under foreign contexts
- low integration cost
- explainability
- stable interfaces

These axes should not be collapsed:

- `R_vertical`: can my direct lineage keep functioning?
- `R_global`: does this artifact help the wider ecosystem?

Vertical persistence can allocate direct continuation. Global adoption can
allocate archive prominence.

### 22.12 Measuring Fitness

Vertical fitness is retrospective and multigenerational. A good seed is not one
that merely copies itself, but one that lets fresh descendants reconstruct the
parent's useful process, remain viable under changed conditions, produce useful
variation, and continue producing viable descendants.

Archive fitness rises when artifacts are adopted across unrelated lineages,
successfully adapted, and retained because they keep helping. Useful measures:

- adoption breadth across unrelated lineages
- success after adaptation
- retrieval frequency corrected for usefulness
- decay under staleness
- explicit budget costs for archive usage
- dependency formation
- consumer-written validation

Producer-written claims can provide provenance and local notes, but durable
public reputation should come mainly from downstream consumers.

### 22.13 Git Ecology Mechanics

Git is storage before it is ecology. It becomes ecology when:

1. Attention is scarce.
2. Retrieval is selective.
3. Integration is costly.
4. Use has consequences.
5. Successful use leaves traces.
6. Artifacts can become dependencies.
7. Stale artifacts decay in visibility.
8. Downstream usefulness matters.

Minimum cultural trace files:

- `USED.md`: what artifacts were used, why they were chosen, whether they
  helped, what was modified, and what future agents should read or avoid.
- `NOMINATIONS.md`: artifacts that deserve higher prominence, with evidence and
  tags/domains.
- `WARNINGS.md`: artifacts that seemed misleading, stale, expensive, brittle, or
  harmful.

Future agents should not read the whole repo. They should start from bounded
recommendations: private lineage seed, selected archive hits, provenance trails,
usage traces, dependency pointers, and trust markers.

### 22.14 Two Views of Cultural Evolution

Agent-centered view:

- Humans or AI rollouts are the reproducing interpreters.
- Artifacts are inherited materials.
- Selection asks which agents or lineages succeed because of what they inherit.
- Useful for lineage continuity, descendant viability, local culture, process
  depth, and multigeneration improvement.

Artifact-centered view:

- Artifacts are replicator-like structures.
- Interpreters are reproduction machinery, carriers, and selective environment.
- Selection asks which artifacts get copied, reconstructed, modified, trusted,
  retained, or depended on.
- Useful for archive competition, cross-lineage spread, cultural fitness,
  memetic drift, dependency formation, reputation, and public artifact survival.

The same system needs both views because artifacts shape agents and agents
produce artifacts.

### 22.15 What Is Under Differential Pressure

Selection acts on whatever has heritable variation and affects its future
representation in the system. Depending on layer, this can be genes, organisms,
agents, artifacts, institutions, seeds, tools, practices, lineages, or process
policies.

Operational questions:

- What varies?
- What is copied or reconstructed?
- What affects future copying or reconstruction?
- What is scarce?
- What is discarded?
- What gets more future influence because it worked?

AI mapping:

- Rollout: ephemeral phenotype/interactor.
- Lineage seed: private vertical cultural inheritance.
- Git artifact: public cultural artifact.
- Agent policy: reconstructed behavior induced by constitution, seed, and
  archive retrieval; indirectly selected through the artifacts that recreate it.

### 22.16 Cross-Inheritance Filters

Cross-inheritance without filters becomes memetic pollution. Filters are needed
because integration is costly, failure is asymmetric, benefit is uncertain, and
downstream consequences can be large.

Possible AI filters:

- retrieval budgets
- trust scores
- provenance requirements
- validation harnesses
- downstream usage logs
- dependency tracking
- staleness decay
- perturbation tests
- archive nomination thresholds
- consumer-written reputation

These are analogues of biological compatibility constraints, regulation,
immune-like filtering, and human peer review, teaching, institutions, citation,
curricula, and professional norms.

### 22.17 Minimal Practical System Picture

Minimal system:

1. A persistent world exists.
2. Each episode starts fresh.
3. A fixed constitution regenerates agent motives and rules.
4. The agent reads the task, lineage seed, selected archive artifacts, and
   bounded recommendations or traces.
5. The agent writes arbitrary files in a temporary workspace.
6. External evaluation decides immediate viability.
7. Successful episodes leave vertical inheritance material.
8. They may nominate artifacts for the global archive.
9. Archive admission is stricter than lineage continuation.
10. Future children draw from both channels, with contributions tracked
    separately.
11. Vertical persistence determines direct lineage continuation.
12. Global adoption determines cross-lineage prominence.
13. Ecological pressure comes from compute limits, context limits, shifting
    tasks, competition, scarce attention, and validation under perturbation.

Four-layer version:

- Constitution / fixed constructor.
- Workspace / lifetime phenotype.
- Lineage seed / vertical culture.
- Git archive / public culture.

### 22.18 Differential Persistence and Consequence

The deepest commonality is differential persistence: a structure persists when
it causes more future instances of itself, or functionally continuous
descendants, to remain in circulation.

The top-level persistence filter can remain simple. What changes is the world
left behind by successful structures. Mechanism:

1. A transmissible structure persists.
2. Its persistence changes the local ecology.
3. The changed ecology rewards additional structure.
4. That additional structure persists if it continues to work under the new
   conditions.

Inheritance alone is not enough. Vertical inheritance alone may produce depth
without novelty. Cross-inheritance alone may produce novelty without depth. Both
can still plateau unless success creates new gradients.

Desired loop:

1. A lineage accumulates vertical depth.
2. It saturates a local strategy.
3. Cross-lineage borrowing or ecological pressure introduces new structure.
4. That structure opens a new vertical trajectory.
5. Resulting successes reshape the competitive and archival environment.
6. New gradients appear.

### 22.19 Practical Problem-Pool Experiment Details

Concrete file layout:

```text
/problems/
  p001.md
  p002.md
  p003.md

/archive/
  tools/
  evaluators/
  notes/
  warnings/
  branches/
  nominations/

/lineages/
  lineage_A/
    gen_001_seed/
    gen_002_seed/
    gen_003_seed/

  lineage_B/
    gen_001_seed/
    gen_002_seed/

/runs/
  raw ephemeral work logs, mostly discarded or compressed
```

Each generation can be framed operationally as a fresh worker. It should choose
promising problems, solve or make progress, record evidence, write a bounded
seed for descendants, nominate globally useful artifacts, and record what helped
or misled it.

The system should not reward only solved-problem count. It should also reward
whether artifacts later runs can actually reuse are produced.

### 22.20 Core Summary

- Base LLM: stable cognitive architecture.
- Constitution: regenerated drives and social motives.
- Lineage seed: vertical inherited culture.
- Git archive: public cross-lineage culture.
- Workspace: individual life.
- Rollout: temporary phenotype/interactor.
- Tasks and budgets: ecology.
- Selection: differential continuation, uptake, trust, reuse, and dependency.

The private seed is not DNA. It is vertically transmitted culture. Git is not
automatically an ecology. It becomes one when artifacts compete for scarce
attention, trust, context, dependency, validation, and downstream use.

The agent-centered view asks which lineages continue. The artifact-centered view
asks which artifacts keep getting reconstructed. Both are required because
agents and artifacts reproduce each other.

### 22.21 Additional Specific Details

Formal self-reference threshold:

- Recursive self-improvement connects to the threshold identified by Godel,
  Turing, and von Neumann: once a formal system can encode statements about
  itself, it admits self-replication, open-ended complexity, and
  undecidability.
- The AI claim is functional rather than mystical: the relevant
  property is representational closure over the substrate, not subjective
  self-awareness.

Fitness shock and biological parallels:

- RNA brute force contrasts with brains' dopamine plus replay as retro-credit
  inside a lifetime.
- The LLM version likely needs something more efficient than either: algorithmic
  redistribution of credit over artifacts, actions, and inherited process.
- "Qm bandit calling" is a mechanism idea for selecting or routing module
  calls. It is not yet developed enough for the main argument, but remains in
  the design-search space.

Weight consolidation analogy:

- RLVR/GRPO already has variation, selection, and partial retention.
- Improvements can compile into weights as habits, sometimes aided by curated
  replay buffers.
- This resembles organism- or behavior-level selection more than gene/word-level
  evolution because inherited subparts do not persist as discrete lineages.

Timeline examples:

- In the biological timeline, substrate machinery stabilizes long before later
  biological explosions; the Cambrian explosion is an example of later
  expansion on top of much older machinery.
- In the cultural timeline, modern brain size predates the behavioral
  explosion, and writing appears much later.
- Writing is described as domain-locked to accounting for a long period before a
  phase transition. Encoding personal names for funerary rites is cited as a
  pressure that helped push writing beyond accounting.

Repetition and display:

- Repetition is not treated as aesthetic by default. It is a compression and
  coordination substrate that makes skill legible.
- In the sexual/social selection branch, fluency, wit, narrative control, and
  recombination of shared units become displays of competence because they show
  internalized command of a shared system.

DGM cost and level:

- DGM-style search is expensive and organism-level. A specific remembered cost
  signature is about `$22k` per run.
- The point is not the exact cost estimate, but the scaling concern: selecting
  whole agent codebases is expensive and gives weak part-level credit.

Optional cycle boundary details:

- The cycle boundary can be tied to writing. Write functions like a stop codon:
  after the model writes a patch or artifact, context wipes and the next cycle
  reads the updated repository state.
- The model can choose actual cycle length within an infrastructure-imposed
  maximum by deciding when to write.
- The target maximum cycle length is an open parameter: too short prevents
  coherent work; too long lets the model solve without externalizing state.

These cycle boundaries are an optional training-oriented implementation detail.

Optional parallel training details:

- Generation remains sequential because each repository state depends on prior
  patches.
- Training can still be parallelized because, after context wipe, every cycle is
  conditionally independent given its repository state.
- Variable-length rollouts produce different numbers of training samples. A
  successful longer rollout trains more cycle decisions, which may be correct if
  many decisions contributed to success.

Optional universal probabilistic Turing machine framing:

- The machine is framed as a universal probabilistic Turing machine with stored
  programs: deterministic execution and stochastic model proposal both operate
  over the same self-referential repository.
- The point is mathematical consistency. Recursive improvement requires both
  transition functions over a substrate that can store the programs,
  instructions, tests, and regulatory documents that affect future transitions.

Archive death by invisibility:

- Unused repository artifacts resemble pseudogenes or obsolete
  dictionary words: they may remain physically stored but no longer get
  transcribed/read.
- The failure mode is not storage bloat alone; it is loss of visibility and
  navigability under bounded reading.

Names and standardization:

- Standardization, dictionaries, schooling, and repair norms are "institutional
  repair enzymes" for human language.
- The AI analogue may include conventions, schemas, READMEs, tests, validators,
  trust files, archive indexes, and consumer-written reputation.

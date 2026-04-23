# Cognitive Language and Artificial Cultural Evolution

Living research document

Version: v0.1 prose draft

Source materials:

- `Cognitive language.docx`
- `Cognitive_Language_Paper_Draft.md`

This draft treats the DOCX as source material and the reconciliation draft as
scaffolding. It is written as a paper-facing argument rather than as notes.

Document stance:

This is not yet a concise formal paper. It is a broad research document intended
to preserve the current theoretical branches, experimental failures, design
constraints, and open questions while the experiments are still incomplete. The
current main sections give the cleanest synthesis so far, but material should
not be deleted merely because it is speculative, redundant, or not yet ready for
publication. For now, unresolved material should be retained, labeled, and moved
to appendices or open-issue sections.

Working editing policy:

- Preserve information unless it is known to be wrong.
- If a claim is uncertain, label its status instead of removing it.
- Keep negative experimental results because they are part of the theory.
- Separate "current synthesis" from "retained branches."
- Defer aggressive compression until the experimental picture is more complete.

## Abstract-Like Current Summary

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
channel can deepen, but neither represents and modifies the rules of its own
future operation. They amplify quantities. They do not build persistent parts
that improve the production, preservation, or recombination of future parts.
Biology and human culture cross a different threshold: their substrates can
represent structures within the system itself.

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
trusted; this naming convention reduces reconstruction cost; this branch should
be continued; this method failed under these conditions.

Such statements are not metadata in the trivial sense. They are regulatory
structure. In a biological analogy, README-like files and indexes act less like
content and more like promoter regions: they influence which stored parts are
read, when, and under what conditions. If whole-run selection rewards tapes that
navigate themselves well, then regulatory documents can be selected indirectly.
The system begins to accumulate not only artifacts, but guidance about which
artifacts matter.

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

This helps explain why reasoning domains with clear verification produce better
chain-of-thought behavior. Verification supplies a selector. It tells the
system which traces worked. But standard verifier-based training still often
selects whole trajectories rather than persistent subparts. Without discrete
inherited units, recurring patterns remain attractors in the model's behavior,
not replicators with identity and lineage.

The goal is to move from trajectory-level selection to process-culture
selection. A successful trajectory should leave behind bounded transmissible
objects that future trajectories can reconstruct and improve. Those objects
should persist only if they continue to help.

## 6. Why Current Module Systems Plateau

The source experiments point to a consistent diagnosis. Providing modules or a
canvas is not enough. The artifacts must be necessary, their use must be
causal, and selection must distinguish helpful inheritance from decorative
mentioning.

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

The context-reset workspace experiment is instructive in the opposite direction.
When file writes triggered context resets, models did externalize state into
files. They produced scripts, notes, calculations, and partial solutions. This
shows that a transmission gap can force externalization. But the resulting
workspace accumulated heterogeneous artifacts without stable naming,
hierarchy, ranking, or cross-problem reuse. Externalization occurred, but
selection over reusable parts was too weak.

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

## 8. The Machine Instantiation

A practical instantiation can be described as a probabilistic machine over a
persistent tape.

The tape is the repository or file system. It contains text, code, tests, notes,
indices, tools, seeds, archive artifacts, and usage traces. The head is a simple
read/write/execute interface, such as a shell. The stochastic transition
function is the model: given the current tape slice and task context, it proposes
actions, file edits, commands, and next artifacts. The deterministic transition
function is execution: tests, verifiers, scripts, compilers, linters, or other
mechanisms that evaluate consequences.

The core loop is:

1. The model reads a bounded view of the tape.
2. It reasons and acts through tools.
3. It writes a patch or artifact.
4. Context wipes.
5. The next cycle starts from the tape.

The context wipe is not incidental. It is the transmission gap. It destroys
unstored internal state and forces any durable progress onto the substrate. If
the maximum cycle context is too large, the model can solve problems without
committing intermediate state, and the tape remains secondary. If it is too
small, the model cannot perform coherent work. The useful regime is long enough
for one meaningful unit of work, but short enough that target problems require
multi-cycle externalization.

As the tape grows, bounded context creates carrying cost. The model cannot read
everything. This creates pressure for regulatory structure: READMEs, indexes,
summaries, dependency maps, trust files, and usage logs that guide future
attention. Files that are never read may remain physically present, but become
functionally dead. Persistence alone is cheap; visibility is scarce.

This gives a route to part-level selection. Files are named, addressable,
persistent, and composable. They can function as parts. Whole-run selection
scores final outcomes, but the outcomes depend on which files were read,
trusted, and modified. Over many tasks, files and regulatory documents that
contribute to successful runs should gain visibility, while misleading or stale
artifacts should lose it.

The key empirical question is whether the regulatory layer develops fast enough
to keep pace with tape growth. If the tape grows faster than the system can
curate it, the result is a junk archive: many persistent artifacts with little
usable heredity. If selection rewards navigable, compact, and useful
organization, the tape can become a process culture.

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

## 11. Conclusion

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

## Appendix A: Working Definitions

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

## Appendix B: Citation Targets

This draft still needs formal citations. Likely citation clusters:

- evolutionary theory and heredity
- cultural evolution and dual inheritance
- iterated learning and compositionality
- external memory, writing, and cumulative culture
- self-reference, formal systems, Turing machines, and von Neumann self-reproduction
- RLVR, GRPO, inference-time scaling, and verifier-based reasoning
- memory-augmented LLM agents and tool-using agents
- Darwin Godel Machine and related evolutionary agent systems
- software repositories, version control, and open-source cultural production

## Appendix C: Source Structure Inventory

This appendix preserves the larger shape of the source document so branches are
not lost while drafting. The current paper-like synthesis should be treated as
one view over this inventory, not a replacement for it.

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
- Clarifies substrate, chunks, and composition rules.
- Stable, referencable, composable units are necessary for cumulative growth.

Part XI, Scale, Depth, and Demonstration:

- Fields deepen because abstractions and external tools improve, not because
  brains grow.
- If knowledge remains externally representable and tool substrates improve,
  depth may continue without an obvious theoretical ceiling.

Part XII, Proto-Language and Suppressed Emergence:

- LLM quirks such as confident nonsense, hallucinated citations, drift,
  verbosity, weak commitment tracking, and schema fragility are predicted
  signatures of fluent symbol manipulation without persistent selection.
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

Part XXI, The Machine:

- AI can be modeled as two loops: inner reader/writer improvement and outer
  substrate accumulation.
- Bash is a universal interface because it lets the model operate in a format
  already present in pretraining.
- The system has two transition functions over the same tape: deterministic
  execution and stochastic model proposal.
- Context wipe forces the tape to carry information forward.
- Wiped cycles make long reasoning potentially linear in depth rather than
  quadratic in sequence length.
- Files provide part-level structure; regulatory documents direct reading.
- The minimal machine implements substrate and constraint, but not the full
  population ecology.

Appendix, Open-Ended RSI as Hereditary Cultural Ecology:

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

## Appendix D: Experiment Ledger

These results are retained because the negative outcomes constrain the theory.
They should not be compressed away until follow-up experiments clarify which
failure modes are structural and which are implementation-specific.

### D.1 Persistent Canvas Substrate

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

### D.2 Dynamic Module Injection Dataset

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

### D.3 Module Extraction from Successful Traces, Random Injection

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

### D.4 Module Extraction plus Ranked Injection

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

### D.5 Usage-Based Module Scoring

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

### D.6 Module Analytics and Summarization

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

### D.7 Selection-Shaped Compositional Vocabulary

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

### D.8 Usage-Weighted Filtered Injection

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

### D.9 Workspace Write-Triggered Context Reset

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

The context wipe successfully forced externalization. It did not, by itself,
create reusable process culture. The missing pieces appear to be naming,
selection, ranking, bounded inheritance, archive filtering, and cross-problem
necessity.

## Appendix E: Retained Theoretical Branches

These branches are not all ready for a concise formal paper, but they should be
kept visible for now.

### E.1 Boundary Principle

Cumulative complexity requires stabilized boundaries. A boundary makes a
substructure identifiable, reusable, preservable, and composable. LLM outputs
currently have many attractors, such as templates and proof moves, but fewer
identity-bearing modules with lineage.

### E.2 Secondary Gradients

Primary selection creates survival. Secondary selection creates architecture.
Once many variants pass the primary filter, constraints among passers create new
fitness gradients. These gradients can favor fidelity, modularity,
compositionality, robustness, and efficient reuse.

### E.3 Transmission-Gap Principle

Vocabulary emerges when useful structure must cross a separation. DNA-protein
separation forces genetic encoding. Speaker-listener separation forces words.
Fresh-context LLM rollouts force process artifacts only if internal state is
destroyed and future continuation depends on external traces.

### E.4 Reader Constraint

The same kind of machinery should write and read the recursively accumulating
substrate. If an LLM writes rigid scripts that are then only read by a Python
interpreter, the model-reader feedback loop weakens. Tools are fine when the
model chooses and interprets their use; rigid workflow scripts can bypass the
cognitive layer.

### E.5 Process Precedes Substrate

The active process historically exists before the persistent substrate it later
depends on. This supports designing for active LLM use first, then letting the
substrate format stabilize under the model's constraint profile.

### E.6 Cross-Layer Native Formats

Each recursive layer operates on outputs of the previous layer but develops a
native representational format suited to its own constraints. LLM-native process
language need not look like human narrative text. It may become denser, more
indexed, and more reconstruction-oriented.

### E.7 Sexual and Social Selection Analogy

Human language and culture may have been accelerated by social and sexual
selection because fluency, wit, narrative control, teaching, and prestige became
high-variance signals. This is relevant as an analogy for AI reputation and
archive uptake, but it is not essential to the core architecture.

### E.8 Pre-RNA and Autocatalytic Chemistry

Pre-RNA chemistry may already show variation, selection, and proto-retention in
reaction networks, surfaces, cycles, and compartments. This supports the idea
that patterns can exist before clean vocabulary. It is useful background but may
belong in a later appendix.

### E.9 Open-Endedness Versus Domain-Specific Accumulation

The minimal machine should not be claimed to produce full open-endedness by
itself. A more defensible short-term target is domain-specific accumulation of
process artifacts that improve solve rates within a bounded bucket. Broader
open-endedness likely requires ecological consequence, shifting tasks,
competition, scarcity, and cross-lineage recombination.

## Appendix F: Open Questions

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

11. What is the minimum context-wipe frequency that forces externalization
    without preventing coherent work?

12. What signs would indicate emergence of a genuine LLM-native process
    language rather than human-readable bureaucracy?

13. Which experimental failures are caused by weak attribution, which by task
    easiness, and which by the absence of ecology?

14. How should deterministic execution and model interpretation be balanced so
    tools help without bypassing recursive cognitive feedback?

15. What counts as falsification for the near-term version of the theory?

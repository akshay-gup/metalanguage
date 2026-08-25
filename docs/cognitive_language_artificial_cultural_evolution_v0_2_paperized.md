# Cognitive Language and Artificial Cultural Evolution

Integrated draft v0.2 - paperization pass

*Editorial status:* This version keeps the constructive theory as the center of the paper and moves most analogy, tooling, landscape, and experiment-ledger material into appendices. The main text should now read as a paper rather than a notebook. The controlling terminology is: **four-layer architecture** plus **two inheritance channels**.

## Abstract

Recursive AI improvement is often framed as a single model modifying itself, its training procedure, its architecture, or its successor. That frame misses the structure shared by the two clearest systems that have accumulated recursive complexity at large scale: biological evolution and human culture. In both cases, accumulation depends on a plastic interpreter coupled to persistent heritable structure under selection. What persists is not the entire lifetime state of an organism or mind, but bounded reconstructible structure that later instances can inherit, reinterpret, vary, and differentially preserve.

This paper develops a selection-theoretic account of **autonomous recursive accumulation**. The central claim is that recursive improvement requires more than storage, memory, or automated labor. It requires heritable process structures that cross transmission gaps and gain future representation because they improve downstream continuation. Storage becomes heredity only when later fresh-context agents depend on it, reconstruct from it, modify it, and preserve it because it helps.

The paper then applies this account to LLM systems. Modern LLMs already have strong interpreter machinery: in-context adaptation, tool use, code generation, critique, summarization, and procedural reconstruction from written cues. What they mostly lack is an AI-native transmission ecology in which model-generated process artifacts persist, compete for scarce attention, shape later fresh rollouts, and are selected by downstream usefulness rather than by producer self-description or human curation.

The constructive proposal is a **four-layer architecture for artificial cultural evolution**: a fixed constructor, an ephemeral workspace, a bounded lineage seed, and a public archive. The lineage seed is vertical culture; the public archive is cross-lineage culture. Selection occurs through protected scoring, bounded context, token or compute costs, archive uptake, descendant performance, and differential continuation. The near-term empirical target is not full open-ended recursive self-improvement, but domain-specific cumulative process evolution tested through fresh-context resets, costly retrieval, lineage/archive baselines, and artifact ablations.

## 1. Introduction and Target of Explanation

Recursive self-improvement is usually imagined as an agent that inspects and rewrites its own mind. The image is intuitive because software is editable, and because a sufficiently capable model appears to be a plausible editor of prompts, tools, code, weights, or successor systems. But the image is incomplete. The cumulative systems we actually know - biological evolution and human culture - are not organized primarily around isolated self-modification. They are hereditary population systems.

Biology does not improve because one organism rewrites itself in place. It improves because heritable structures persist across generations, vary, and are selected through the success of organisms that reconstruct and express them. Human culture does not accumulate because one mind stores and perfects all knowledge. It accumulates because speech, writing, tools, institutions, records, and practices allow useful structures to outlive any one mind, be reconstructed by other minds, and be modified under material, social, and institutional selection.

The shared pattern is not intelligence alone. It is externalized heredity. A fast, plastic process acts in the world and leaves traces. Some traces become stable enough to be read by later processes of the same general kind. Those later processes reconstruct useful behavior from the traces, vary it, test it, and rewrite the substrate. The loop can then improve not only its immediate outputs but also the conditions under which future outputs are generated.

LLM systems already possess much of the active side of this loop. A modern model can infer task-local rules from context, write and run code, critique an answer, summarize evidence, compose tools, and reconstruct procedures from sparse instructions. These are powerful interpreter capabilities. Yet they mostly die with the episode. Chain-of-thought traces are not normally inherited. Temporary scripts are not normally selected across generations. Memory stores can accumulate text, but a stored note is not heredity unless it causally shapes later behavior and is retained or modified because it helped.

The target of this paper is therefore not ordinary model improvement, better memory, or AI-assisted research acceleration. The target is **autonomous recursive accumulation**: a system in which structures generated inside the system become inherited conditions for future instances and are differentially preserved because they improve future continuation.

Open-endedness and recursion are distinct properties. A system may recursively improve within a bounded domain without generating an expanding range of novelty, while a system may generate sustained novelty without improving the machinery that produces it. The target here is their conjunction: cumulative novelty that changes how subsequent novelty is generated, transmitted, interpreted, evaluated, or combined. On this stronger criterion, an improvement is recursively relevant only when it changes the machinery or inherited process by which future improvements are produced, rather than merely improving an object-level output.

The key question is:

> What minimal architecture would allow AI-generated process structures to become heritable, selectable, and cumulative without relying on a privileged human curator at every cycle?

This is not a proposal for giving LLMs more memory. It is a proposal for turning externalized process into heritable culture by making future fresh-context agents depend on bounded artifacts under scarcity, evaluation, and differential continuation.

### Main contribution

The paper makes three linked contributions. First, it gives a selection-theoretic account of recursive accumulation as heritable process structure crossing transmission gaps under protected selection. Second, it diagnoses current LLM systems as strong interpreters without an AI-native transmission ecology: they can read, write, test, and reconstruct process, but their useful procedural traces rarely become load-bearing across fresh-context boundaries. Third, it proposes a four-layer artificial-cultural-evolution architecture - fixed constructor, ephemeral workspace, bounded lineage seed, and public archive - together with empirical tests that distinguish real heredity and uptake from storage, injection, mention, or memory theater.

### Claims ladder

The argument should be read as a ladder, not as a single maximal assertion.

1. **Conceptual correction.** Recursive improvement should not be modeled primarily as isolated self-modification. The known cumulative systems are hereditary and ecological.
2. **Functional requirement.** Autonomous recursive accumulation requires enabling conditions such as stable interpretation, persistent substrate, transmission gaps, heritable variation, scarcity, protected selection, and differential continuation.
3. **LLM diagnosis.** LLMs already have strong interpreter machinery but weak AI-native transmission ecology.
4. **Architecture.** A four-layer architecture of fixed constructor, ephemeral workspace, lineage seed, and public archive can operationalize artificial cultural evolution.
5. **Empirical prediction.** Under bounded context, costly attention, and descendant-based selection, lineage seeds and archive artifacts should become more compact, reconstructible, modular, and uptake-sensitive over generations.
6. **Near-term scope.** The first empirical target is domain-specific cumulative process evolution, not immediate open-ended recursive self-improvement.
7. **Stronger future claim.** A human-free recursive AI system would require replacing human selection with protected artificial consequence, not merely automating research labor.

## 2. The Two-Loop Structure of Cumulative Systems

A cumulative system must solve two opposed problems. It must be plastic enough to search, learn, and adapt. It must also be persistent enough to retain what worked. These requirements pull against each other. A substrate that changes too easily forgets; a substrate that resists change too strongly cannot learn.

Known cumulative systems handle this by splitting into two coupled loops. The inner loop is active and plastic. It reads, interprets, searches, and acts. The outer loop is persistent and selective. It stores structures that can outlast a single episode, organism, or mind. Recursion lives in the coupling: better readers and writers create better stored structure, and better stored structure makes future reading and writing more effective.

In biology, cellular machinery reads and expresses genetic material. Organisms are transient interactors in an environment. Genomes and inherited cellular organization persist across generations and change under selection. In human culture, brains are the plastic machinery. Speech, writing, diagrams, mathematics, code, tools, institutions, and archives are persistent cultural substrates. No individual mind contains the whole culture. Minds reconstruct fragments of culture, use them, modify them, teach them, and leave traces for other minds.

The AI analogue should preserve this separation. The base model and scaffold are the stable interpreter machinery. A rollout is an episode of plastic action. A workspace is the episode's local lifetime state. A persistent repository or archive is the substrate. A lineage seed is the bounded vertical process packet passed from parent to child. A public archive is the shared cultural store from which unrelated lineages can borrow.

Von Neumann's description-constructor distinction clarifies why the persistent side of the loop is powerful. A hereditary description can be copied without being executed and interpreted to reconstruct active machinery. Copying preserves the description across turnover; interpretation turns it into causal process. Because descriptions can be copied, varied, recombined, compared, and corrected more readily than fully assembled machines, they provide an addressable channel for cumulative variation. Genetic descriptions instantiate this pattern directly; cultural instructions and machine-readable artifacts are looser functional analogues.

The seed is not DNA in a literal sense. It is closer to vertically transmitted culture: lab notes, operating doctrine, apprenticeship material, local conventions, trusted tools, warnings, and unresolved hypotheses. The base model, system prompt, tool scaffold, and evaluation harness are closer to the fixed constructor that regenerates a certain kind of agent each episode. Git or any shared archive is not automatically an ecology. It becomes ecological only when artifacts compete for attention, trust, dependency, validation, context, execution cost, and downstream use.

The design principle is:

```text
Fix the constructor.
Fix the minimal protocol and scarcity.
Let the process culture evolve.
```

The constructor must be stable enough that descendants can interpret inherited material. The protocol must be minimal enough not to freeze the representational language too early. The ecology must be selective enough that stored artifacts do not merely accumulate as debris.

### Self-reference without mysticism

This framework is related to classical questions of self-reference, self-reproduction, and formal systems, but the present claim is operational. A substrate becomes recursively improvable when it can contain model-readable artifacts about its own future use, maintenance, revision, evaluation, and transmission.

The relevant threshold is **representational closure over the process substrate**, not subjective self-awareness. A repository can contain code, documentation, tests, scripts, READMEs, dependency graphs, evaluation records, warnings, indexes, deprecation notes, and instructions for future agents about how to interpret and modify the repository. These artifacts can regulate which other artifacts are read, trusted, revised, preserved, or ignored. When such regulatory structure is itself selected by downstream usefulness, the system can accumulate guidance about its own continuation.

This is why ordinary memory is insufficient. A passive memory store may help retrieval, but recursive accumulation requires stored structure that guides future reading, writing, selection, and revision of stored structure. The system must be able to preserve claims such as: this artifact helps this class of problems; this convention reduces reconstruction cost; this tool is stale; this evaluator is trusted only under these conditions; this lineage should continue; this archive branch should decay.

## 3. Necessary Conditions for Autonomous Recursive Accumulation

A system can show local improvement without satisfying the conditions for autonomous recursive accumulation. The following conditions are best read as **necessary or enabling conditions**, not as sufficient guarantees of open-endedness.

**Stable interpreter.** There must be a relatively stable class of machinery capable of reconstructing process from inherited structure. If the interpreter changes too quickly, inherited artifacts lose meaning.

**Persistent substrate.** There must be a medium in which process-relevant structures can survive beyond a single episode, organism, mind, or rollout.

**Transmission gap.** Internal state must not carry over automatically. A gap must force useful process to be externalized, compressed, and reconstructed by later instances.

**Heritable variation.** Inherited structures must vary, and descendants must resemble ancestors enough for successful variants to have lineage.

**Part-level visibility.** Useful substructures must become identifiable enough to be copied, modified, recombined, tested, or discarded. Whole-system success alone gives weak accumulation.

**Scarcity.** Attention, context, compute, continuation, or visibility must be limited. Without scarcity, poor artifacts persist alongside useful ones and selection weakens.

**Protected selection.** The current variant must not be able to freely redefine the criterion by which its own continuation is judged. Some consequence layer must remain fixed or slow-changing.

**Differential continuation.** Structures that improve future success, robustness, efficiency, or option value must receive more future influence than structures that do not.

**Downstream uptake.** Artifacts must be evaluated primarily by later use, not producer self-description. Exposure and mention are weak signals; adoption, dependency, modification, and ablation-sensitive contribution are stronger signals.

**Plasticity-persistence balance.** The system must allow enough mutation and recombination to discover improvements, but enough fidelity and stability to retain them.

A compact minimal condition can be stated as follows. Let `a_i` be an inherited artifact or process structure, and let `q_i(t)` be its future representation: retrieval probability, inclusion in seeds, dependency status, lineage continuation, archive visibility, or compute allocation. Adaptive accumulation requires:

```text
q_i(t + 1) increases when a_i causally improves downstream continuation.
```

Equivalently:

```text
Cov(effect(a_i), future_representation(a_i)) > 0
```

This is not a theorem of open-endedness. It is a minimal adaptive-accumulation condition. Without it, a system may store, mention, or imitate artifacts, but it is not adaptively accumulating them.

The persistence-plasticity constraint can be summarized as follows.

| System | Plastic interpreter | Persistent substrate | Selection layer | Status if complete |
| --- | --- | --- | --- | --- |
| Biology | organism and cell activity | genome and inherited cellular organization | environment-mediated reproduction | cumulative adaptation |
| Human culture | brains, social learning, institutions | speech, writing, tools, practices, records | material, social, and institutional uptake | cumulative culture |
| Current AI labs | models plus human researchers | code, data, evals, checkpoints, docs | human and institutional judgment plus benchmarks | hybrid improvement |
| Proposed AI ecology | fresh LLM rollouts | lineage seeds and public archive | protected scoring, scarce attention, differential continuation, uptake | artificial cultural evolution |

The proposed architecture is not trying to mimic DNA literally. It is trying to satisfy the same persistence-plasticity constraint at the process level. Fresh rollouts supply plasticity. Seeds and archives supply persistence. Primitive physics and uptake supply selection. Bounded context and fresh starts create the transmission gap that makes externalized process necessary.

## 4. LLMs as Strong Interpreters Without Transmission Ecology

LLMs should not be understood as weak imitations of human cognitive machinery. They have a different constraint profile. A human reader is slow, serial, and shaped by long-term memory. Re-reading is costly, so human culture developed narrative, pedagogy, and memory-supporting forms suited to slow serial readers. An LLM can ingest thousands of tokens in one episode, integrate large local contexts, call tools, and reconstruct procedures quickly. Its weakness is not the same as human working memory. Its weakness is the lack of durable carryover across episodes.

This makes in-context learning, chain-of-thought, roles, structured output, and tool use look different. They are not merely inferior versions of human memory, writing, institutions, or protocols. They are native mechanisms for high-bandwidth within-episode adaptation. In-context learning reconstructs local state from the prompt. Chain-of-thought provides a temporary computation scaffold. Roles induce mode shifts. Structured output makes actions interoperable with tools and external systems.

But these mechanisms are mostly episodic. They do not by themselves create lineages. A chain-of-thought trace can help solve a problem, but if it is not externalized in a form future runs can use, it is not inherited. A tool can be created during a run, but if no later run retrieves, trusts, adapts, or depends on it, it is not culturally selected. A memory can be stored, but if future agents are not forced to choose among memories under cost and consequence, the store is not an ecology.

The missing layer is therefore not "more context" alone. More context can even weaken the pressure to externalize by making the transmission gap less binding. The missing layer is selective persistence of process across fresh contexts. The system must make external artifacts necessary for continued success, and it must make poor artifacts costly.

This also explains why ordinary LLM use rarely produces stable invented vocabularies, dialects, or compact process conventions. Models can create local shorthand inside a context, but the shorthand is not transmitted through a persistent ecology with uptake pressure. External readability constraints often reward legibility to humans or benchmarks rather than compact transmissible process representation for future model instances.

Reasoning domains with clear verification show a partial version of the missing selector. Verification can reinforce traces that help reach correct answers. But standard verifier-based training often selects whole trajectories rather than persistent subparts. Without discrete inherited units, recurring patterns remain attractors in model behavior, not replicators with identity and lineage.

The goal is to move from trajectory-level selection to process-culture selection. A successful trajectory should leave behind bounded transmissible objects that future trajectories can reconstruct and improve. Those objects should persist only if they continue to help.

### Storage is not heredity

The central contrast is not memory versus no memory. It is storage versus hereditary consequence.

A stored artifact becomes hereditary only when:

1. a later fresh-context agent encounters it across a transmission gap;
2. the agent depends on it enough that withholding, corrupting, or pricing it changes performance;
3. the artifact or a descendant version is carried forward because it helped;
4. future representation of the artifact increases through downstream usefulness rather than producer claims.

This distinction explains several failures of module and memory systems. Optional modules may reduce token use without improving reward. Injected artifacts may be mentioned without being used. Workspaces may accumulate files without part-level selection. A model can perform "module use" as a ritual if the metric rewards mention rather than causal contribution. In all of these cases, storage exists, but heredity has not yet formed.

## 5. Architecture for Artificial Cultural Evolution

The constructive proposal is a four-layer architecture with two inheritance channels.

### 5.1 Four layers

**1. Fixed constructor.** This layer is stable or slow-changing across rollouts. It includes the base model, system prompt or constitution, tool interface, primitive rules, evaluation harness, and basic scarcity constraints. The constructor should initially be fixed because descendants need a stable interpreter.

**2. Ephemeral workspace.** This is the rollout's temporary lifetime state. It contains task information, local scratch files, generated scripts, intermediate notes, tool outputs, and attempted solutions. It is writable and flexible, but it is not inherited wholesale. A full workspace dump is too noisy to be a clean heredity object.

**3. Lineage seed.** This is bounded vertical culture passed from parent to child. It may include operating doctrine, useful procedures, trusted archive pointers, warnings, problem maps, unresolved hypotheses, evaluator notes, and mutation suggestions. It is not DNA. It is closer to apprenticeship notes, lab doctrine, local tradition, or a compact handoff packet.

**4. Public archive.** This is cross-lineage culture. It contains tools, notes, evaluators, problem framings, warnings, branches, recommendations, dependency graphs, and artifacts nominated for broad reuse. It becomes an ecology only when artifacts compete for scarce attention, trust, context, dependency, validation, execution cost, and downstream use.

The two inheritance channels are the lineage seed and the public archive. They should not be collapsed. Vertical inheritance selects for continuity, reconstructibility, local coherence, and mutational headroom within a lineage. Cross-lineage inheritance selects for portability, interoperability, discoverability, low integration cost, and usefulness under foreign contexts.

Vertical inheritance without cross-lineage borrowing risks narrow depth. Cross-lineage borrowing without vertical continuity risks shallow novelty. Together they create a cultural system with both depth and breadth.

### 5.2 Primitive physics versus evolved filters

The architecture should fix consequence, not doctrine. If every trust rule, archive filter, reputation mechanism, artifact format, evaluator convention, role, and review practice is specified in advance, the result is a human-designed institution rather than an evolving process culture. But if nothing is fixed, agents can drift, self-certify, preserve useless artifacts, or redefine success.

The fixed or slow-changing **primitive physics** includes fresh episode starts, bounded context, bounded seed size, bounded archive retrieval, compute and attention costs, current-run scoring that the current run cannot rewrite, and continuation or visibility tied to downstream consequence.

Above that layer, cultural filters may evolve: trust rules, provenance norms, deprecation procedures, archive conventions, review practices, dependency policies, warning formats, evaluator-building traditions, problem taxonomies, and seed-writing conventions.

The compact rule is:

```text
Fix consequence, not doctrine.
```

### 5.3 Minimal algorithm

```text
Initialize:
  Fixed constructor C
  Active population of lineages L
  Public archive A
  Problem ecology E
  Bounds for context, archive retrieval, compute, and continuation slots

For each generation:
  For each selected parent lineage l in L:
    Spawn k fresh rollout children.

    For each child r:
      Reset hidden state.
      Provide:
        - fixed constructor C
        - current task or problem slice from E
        - bounded parent lineage seed S_l
        - small selected archive slice R(A)
        - ephemeral writable workspace W_r

      Run r under bounded compute/context/tool costs.
      Score immediate task progress with protected evaluator V.
      Require r to write:
        - candidate next_seed.md
        - evidence log
        - uptake log: artifacts used, ignored, modified, or found misleading
        - nominations or warnings for public archive

    Select candidate child seeds by immediate viability.
    Put selected seeds into probation.
    Allocate descendant opportunities according to delayed descendant performance.

  Update archive visibility:
    Increase visibility for artifacts adopted by successful downstream consumers.
    Decrease visibility for ignored, stale, misleading, costly, or failure-linked artifacts.
    Do not strongly reward exposure, producer claims, or string mention.

  Update lineage continuation:
    Give more future rollouts to seeds whose descendants perform better,
    cost less, recover better, or preserve useful option value.
    Preserve exploration with bootstrap refill for young, unusual, or under-sampled lineages.
```

This algorithm is deliberately minimal. It does not hand-design the final process-representation format. It fixes the medium, inheritance path, scarcity, and scoring channels. Agents can invent notes, scripts, manifests, dependency graphs, skills, retrieval guides, evaluator packages, branch rituals, or other formats. The system dictates inheritance, execution, and scoring, not syntax.

### 5.4 Rollout-owned continuation

Uniform continuation is weak. If every rollout receives the same descendants,
inheritance quality and artifact production are only weakly selected.
One reserved child opportunity per rollout makes successor construction
consequential independently for each source: a lineage continues from that
rollout only if it produces a usable handoff. Bootstrap refill restores every
configured population position without a spawned child so exploration does not collapse.

This continuation rule alone is not open-ended ecology. It becomes ecological
only when successful artifacts alter future conditions by becoming dependencies,
shortcuts, standards, risks, interfaces, or maintenance obligations for later
agents. The goal is future option value under bounded attention and changing
constraints.

## 6. Fitness, Uptake, and Differential Continuation

Selection acts on whatever has heritable variation and affects its future representation in the system. Depending on the layer, this can be lineages, seeds, tools, archive artifacts, evaluators, naming conventions, trust markers, retrieval policies, or broader process strategies.

The basic operational questions are:

```text
What varies?
What is copied or reconstructed?
What affects future copying or reconstruction?
What is scarce?
What is discarded?
What receives more future influence because it worked?
```

### Vertical fitness

Vertical fitness asks whether a direct lineage can continue. A good seed is not one that merely copies itself; it is one that lets fresh descendants reconstruct the parent's useful process, remain viable under changed conditions, produce useful variation, and continue producing viable descendants.

Useful vertical signals include descendant solve rate, descendant recovery from perturbation, cost reduction, seed reconstructibility, ability to handle shifted task variants, avoidance of seed bloat, and multigeneration continuation.

### Archive fitness

Archive fitness asks whether unrelated lineages retrieve, adapt, validate, and benefit from an artifact. The analog of reproduction is not biological offspring but future influence: retrieval probability, recommendation prominence, dependency status, inclusion in seeds, adaptation into new versions, and survival through deprecation pressure.

The archive should distinguish exposure, attention, and uptake.

**Exposure** means the artifact was available. **Attention** means a later run inspected it. **Uptake** means a later run incorporated, copied, adapted, executed, depended on, or carried it forward in a way associated with downstream success.

Only uptake should strongly affect artifact fitness. Search hits, brief reads, producer-written claims, and string mentions are weak signals. A practical first rule is that an artifact counts as adopted only if it is carried into a child seed, copied or modified into a derivative artifact, imported as a dependency, used by an evaluator or workflow, or nominated by a downstream consumer with evidence.

This does not require perfect causal attribution. Natural selection does not know perfect causal credit; it uses repeated consequence. The archive can start with noisy but grounded association: artifacts carried forward by successful unrelated lineages gain visibility; artifacts carried forward by failing lineages lose visibility; artifacts marked misleading by consumers decay; artifacts that are only exposed or mentioned gain little standing.

### Failure modes as design tests

The most important failure modes are not side issues; they are the tests the architecture must pass.

Seed bloat means seeds become long, vague, and expensive to reconstruct. Ritual documentation means agents write handoff reports because prompted, but descendants do not use them. Archive spam means lineages flood the public store with artifacts. Producer self-promotion means lineages claim usefulness without downstream evidence. Popular but brittle artifacts spread because they are easy to understand, not because they are robust. Static benchmark plateau means the system optimizes a fixed task distribution without creating new gradients. Metric capture means agents alter what counts as success.

The counterpressures are bounded seeds, descendant performance, retrieval costs, archive decay, consumer-written uptake, perturbation tests, uneditable current-run scoring, delayed validation for evaluator changes, and bootstrap exploration for unusual lineages.

## 7. Experiments and Falsifiers

The first empirical target should not be full open-ended recursive self-improvement. A more defensible target is **multi-generation process accumulation inside a bounded problem ecology**.

The central empirical question is:

> Can a population of fresh-context LLM rollouts, given bounded lineage seeds and selected archive artifacts, accumulate reusable process structure faster than isolated rollouts, full workspace carryover, optional module injection, seed-only systems, archive-only systems, or seed-plus-archive systems without selection?

A minimal experiment maintains a persistent problem pool and multiple lineages. Each generation receives a fresh context, a fixed constructor, a bounded lineage seed, and a small selected archive slice. The rollout works in an ephemeral workspace, attempts tasks, records evidence, writes a next seed, and nominates or warns against public artifacts. Immediate task performance is scored by tests or verifiers. Descendant performance measures vertical fitness. Validated uptake by unrelated lineages measures archive fitness.

The key baselines are:

1. no memory;
2. full workspace carryover;
3. optional module injection;
4. bounded lineage seed only;
5. public archive only;
6. lineage seed plus public archive without uptake-sensitive selection;
7. lineage seed plus public archive with uptake-sensitive selection.

The key measurements are multi-generation solve-rate improvement, seed reconstructibility under fresh-context reset, descendant viability under perturbation, cross-lineage artifact adoption corrected by downstream success, reduced redundant artifacts, emergence of stable naming and indexing conventions, archive retrieval precision under bounded context, artifact dependency formation, and cost-adjusted performance.

### Local consequence and external assays

Selection inside the ecology and measurement of the ecology should be separated. Local tests, verifiers, descendant performance, and downstream uptake can provide protected in-loop consequence: they determine whether a particular solution, seed, or artifact remains useful. They need not collapse into a single permanent global objective. Deep artifact chains can instead be evaluated through local consumer relations - a tool helps a workflow, a workflow helps a solver - while external task performance supplies the boundary condition.

Global benchmarks should be treated as blind held-out assays rather than exposed objectives. At intervals, the artifact ecology should be frozen and fresh evaluation rollouts should receive bounded access to it on held-out tasks. Their performance should be compared with matched rollouts that lack the ecology, and neither the assay tasks nor their outcomes should be returned directly to the active selection loop. This tests whether inherited culture causally expands capability rather than merely accumulating text or adapting to a visible score.

### Ablation-sensitive evidence

The most important measurement is not whether agents mention artifacts. It is whether descendants become worse when the inherited artifact is withheld, corrupted, paraphrased, priced, or replaced.

Required ablations include:

1. artifact removed;
2. artifact corrupted;
3. artifact paraphrased;
4. artifact replaced with irrelevant artifact;
5. retrieval made costly;
6. seed size tightened;
7. archive visibility randomized;
8. fresh-context reset enforced;
9. artifact attribution hidden;
10. artifact exposed but made non-importable or non-executable.

A load-bearing artifact should show causal sensitivity. Withholding or corrupting it should degrade descendants relative to controls. Paraphrasing should preserve effect if the relevant structure is semantic or procedural rather than string-specific. Raising retrieval cost should reduce use unless the artifact's expected downstream value justifies the cost. Randomizing archive visibility should weaken uptake if archive selection is doing real work.

### Falsifiers

The main near-term falsifier is:

> If bounded lineage seeds and selected archive artifacts do not improve descendant performance relative to baselines under fresh-context reset, retrieval-cost pressure, and artifact-ablation tests, then the artificial-cultural-evolution claim is not supported in that domain.

Additional falsifiers:

- If artifacts are frequently read or mentioned but removing them does not harm descendant performance, the system has storage or mention, not heredity.
- If full workspace carryover consistently outperforms bounded seeds under cost and perturbation, then the proposed transmission bottleneck may be too severe or the domain may not reward compression.
- If seed-only systems improve but archive systems do not, vertical culture may be sufficient for the domain and cross-lineage culture is not yet load-bearing.
- If archive-only systems improve but lineages do not, the system may be selecting generic tools rather than cumulative traditions.
- If uptake-sensitive selection produces more artifacts but not better descendants, the attribution mechanism is likely selecting popularity, self-promotion, or ritual use.
- If inherited artifacts help only when tasks repeat exactly and fail under modest perturbation, the system is memorizing task instances rather than accumulating reusable process.
- If retrieval cost eliminates artifact use entirely, the archive has not produced value high enough to overcome bounded attention.

The strongest positive result would not simply be better one-step benchmark performance. It would be evidence that fresh descendants continue a process more effectively because of bounded inherited seeds, and that unrelated lineages benefit from selected archive artifacts without reading the whole archive.

## 8. Discussion: Scope, Limits, and Relation to Current AI R&D

This paper is constructive rather than polemical. Current AI-lab improvement loops already contain parts of the proposed pattern. Models generate candidate ideas, code, synthetic data, evals, curricula, debugging strategies, and infrastructure improvements. Labs test some candidates, preserve successful changes in code, data, evals, checkpoints, and documentation, and incorporate them into later systems.

This is a real cumulative loop, but the unit of accumulation is not the model alone. It is a hybrid system: model, humans, datasets, codebase, evals, compute, institutional judgment, and training pipeline. Humans remain load-bearing as selectors. They decide which proposals are worth testing, which evals matter, which failures are meaningful, which gains are real, and what "better" means.

Reducing human labor does not automatically remove human selection. Automating code writing, experiment execution, data generation, or report production reduces the cost of variation and testing. It does not by itself create an autonomous selection ecology. Removing humans as selectors would require protected, grounded, system-internal consequence: bounded resources, uneditable current-run scoring, downstream uptake, lineage continuation, archive decay, and task or environment feedback.

This is also why a training recipe should not be treated as an AI genome. A frontier training run depends on datasets, filtering rules, optimizer settings, infrastructure, evaluation culture, debugging lore, human judgment, hardware constraints, safety policies, and undocumented institutional practice. It is not a compact self-reproducing description automatically copied and interpreted by a stable constructor. Weight updates may consolidate discoveries, but training is one possible consolidation pathway for process structures discovered by a broader hereditary ecology; it is not the whole recursive substrate.

The language claim should also be read cautiously. The paper does not claim that all persistent representation is literally language, nor that LLMs must invent a new human-like language. The claim is conditional: under finite media, bounded readers, lossy reconstruction, scarce attention, and selection for reuse, scalable process substrates are pushed toward **language-like process structure** - discreteness, compositionality, hierarchy, naming, convention, and self-reference. The more general term is **transmissible process representation**.

Finally, the necessary conditions in this paper are not sufficient for open-endedness. They define the enabling substrate for adaptive accumulation. Broader open-endedness may require dynamic landscapes, shifting tasks, ecological feedback from prior success, parasites or exploiters, multi-agent competition, cross-lineage recombination, resource transfer, and new organizational levels. The near-term goal is narrower and testable: show that bounded inherited process artifacts become load-bearing under fresh-context reset, costly attention, protected selection, and descendant-sensitive continuation.

The main thesis is therefore constructive:

> Recursive AI, if it becomes autonomous, will likely require a hereditary process ecology: stable constructors, fresh rollouts, bounded seeds, public archives, protected selection, scarce attention, downstream uptake, and differential continuation.


# Appendices

*The appendices preserve the dense source material from v0.1. The main text controls the final terminology and the level of claim; appendix sections are retained as extended notes, mechanisms, edge cases, and experiment records.*


## Appendix A. Biological and Cultural Analogies


### Vehicle, Use, and Two-Fold Selection

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


### Co-Evolution Rather Than Encoding Pre-Existing Complexity

Complex structure does not appear first and then get encoded wholesale.
Historical pattern:

- RNA begins with short replicating sequences, and complexity grows with
  replication fidelity.
- Language begins with simpler signals, while complex syntax appears much later.
- Writing begins with tallies and accounting, while philosophy and mathematics
  arrive later.

Vocabulary and complexity co-evolve. For AI, this argues against requiring a
complete process-representation format in advance. Start with simple transmissible structures
under real selection and let complexity grow with fidelity, necessity, and
reuse.


### Externalization Ladder and Nested Selection

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


### Fitness Shock and Biological Parallels

- RNA brute force contrasts with brains' dopamine plus replay as retro-credit
  inside a lifetime.
- The LLM version likely needs something more efficient than either: algorithmic
  redistribution of credit over artifacts, actions, and inherited process.
- "Qm bandit calling" is a mechanism idea for selecting or routing module
  calls. It is not yet developed enough for the main argument, but remains in
  the design-search space.


### Blind Search, Structured Search, and Routing Around Slow Loops

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


### Visibility Threshold

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


### Boundary and Selection Regimes

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


### Pre-RNA Hand-Off and Boundary Hardening

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


### Secondary Gradients and Crisis Pattern

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


### Substrate Stabilization and Universality

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


### Step 0 in Biology and Culture

The minimal origin pattern is smaller than mature biological or cultural
ecology. Biology begins with fixed physical laws, energy flow, time, variation,
and persistence. Culture begins with fixed human biology, material needs,
resource flow, learning variation, and persistence through memory, imitation, and
records. Complex organisms, language, tools, institutions, and sciences appear
only later.

Both systems combine individual limits with system-level abundance. Organisms
have bounded bodies and lifetimes; humans have bounded attention and working
memory. Yet energy, problems, and social opportunities continue beyond any
single instance. Fresh instances inherit from exhausted ones, so bounded lives
can still support cumulative structure.

Both systems also connect resource conversion to continuation. Organisms that
obtain more usable energy tend to leave more descendants. Cultural groups and
organizations that convert resources into useful work tend to recruit, copy,
teach, hire, or found successors. This is not a guarantee of adaptive complexity;
it is a pressure by which efficient persistence can compound.

Transfer mechanisms appear early. Energy moves through predation, parasitism,
and symbiosis. Human resources move through trade, theft, inheritance, taxation,
employment, and patronage. The mature institutions differ, but the primitive
fact is shared: resources can move between bounded actors, and those transfers
reshape the local ecology.


### Timeline Examples

- In the biological timeline, substrate machinery stabilizes long before later
  biological explosions; the Cambrian explosion is an example of later
  expansion on top of much older machinery.
- In the cultural timeline, modern brain size predates the behavioral
  explosion, and writing appears much later.
- Writing is described as domain-locked to accounting for a long period before a
  phase transition. Encoding personal names for funerary rites is cited as a
  pressure that helped push writing beyond accounting.


### Sexual and Social Selection Analogy

Human language and culture may have been accelerated by social and sexual
selection because fluency, wit, narrative control, teaching, and prestige became
high-variance signals. This is relevant as an analogy for AI reputation and
archive uptake, but it is not essential to the core architecture.


### Repetition and Display

- Repetition is not treated as aesthetic by default. It is a compression and
  coordination substrate that makes skill legible.
- In the sexual/social selection branch, fluency, wit, narrative control, and
  recombination of shared units become displays of competence because they show
  internalized command of a shared system.


### Pre-RNA and Autocatalytic Chemistry

Pre-RNA chemistry may already show variation, selection, and proto-retention in
reaction networks, surfaces, cycles, and compartments. This supports the idea
that patterns can exist before clean vocabulary.


## Appendix B. Language-Like Convergence and MNFL


*Terminology note:* the main text uses **transmissible process representation** as the broad term and **language-like process structure** for the convergence claim. This appendix preserves the detailed reasoning behind that convergence claim while softening claims that all persistent representation is literally language.


### Self-Referential Representation and Language-Like Process Structure

The main text uses "transmissible process representation" as the broad term and reserves "language-like" for the narrower convergence claim. In this appendix, "language-like process structure" means a discrete, compositional, self-referential representation that can be read, written, reused, and modified by the same class of machinery that depends on it.

This definition includes human symbolic language, but it is not limited to it.
Genetic sequences are language-like in this functional sense because they are
discrete, compositional, persistent, and interpreted by cellular machinery that
they also help specify. Mathematics and programming languages are language-like
because they provide named reusable structures, composition rules, and
self-referential operations. The question for LLM systems is whether they can
develop language-like process structure: compact external artifacts that allow fresh runs to
reload useful state, choose actions, use tools, evaluate progress, and continue
improvement.

Self-reference is the key property. A wildfire can spread, and an erosion
channel can deepen, and ice-albedo feedback can amplify a climate state, but
none represents and modifies the rules of its own future operation. They amplify
quantities. They do not build persistent parts that improve the production,
preservation, or recombination of future parts. Biology and human culture cross
a different threshold: their substrates can represent structures within the
system itself.

This is the ratchet distinction. Language-like process representation is not just a label for communication;
it is the manufacturing capability for reusable parts. Without a combinatorial
system, a process cannot reliably produce discrete reusable units. Without
reusable units, it cannot accumulate. The self-referential version of transmissible process representation
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


### Formal Self-Reference Threshold

This framework is adjacent to classical questions of self-reference in formal
systems, computation, and self-reproduction, but the claim here is narrower and
operational. The paper should not argue that formal self-encoding by itself
produces open-endedness. Instead, the relevant threshold is representational
closure over the process substrate: the substrate can contain artifacts about
its own reading, writing, testing, maintenance, revision, evaluation, and
transmission.

The AI claim is therefore not mystical and not a claim about subjective
self-awareness. A recursively improvable process ecology requires
model-readable structures that can guide how future model instances interpret,
modify, trust, prune, and preserve the same substrate. Such self-reference is
necessary for substrate-level recursion, but it is not sufficient for
open-endedness without heredity, scarcity, protected selection, and downstream
uptake.


### Why Language-Like Structure Converges

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
available within its bounded context and retrieval allowance. The gap forces the
system to encode process into persistent artifacts. If those artifacts are under
selection, the pressure should favor compact, modular, reconstructible process
representations.


### Boundary Principle

Cumulative complexity requires stabilized boundaries. A boundary makes a
substructure identifiable, reusable, preservable, and composable. LLM outputs
currently have many attractors, such as templates and proof moves, but fewer
identity-bearing modules with lineage. Current chunk examples include
rhetorical scaffolds, format templates, proof moves, tool-call rituals, and
safety boilerplate: recurrent motifs that can be useful, but are not yet stable
replicators.


### Secondary Gradients

Primary selection creates survival. Secondary selection creates architecture.
Once many variants pass the primary filter, constraints among passers create new
fitness gradients. These gradients can favor fidelity, modularity,
compositionality, robustness, and efficient reuse.


### Transmission-Gap Principle

Vocabulary emerges when useful structure must cross a separation. DNA-protein
separation forces genetic encoding. Speaker-listener separation forces words.
Fresh-context LLM rollouts force process artifacts only if internal state is
destroyed and future continuation depends on external traces.

The negative cases matter. Pre-cellular chemistry has recurring patterns, but
the molecule does not refer to something else; it simply is the structure.
Standard RLVR has the same model and same weights across attempts, so there is
no transmission gap that forces vocabulary-like artifacts. Without separation,
there can be patterns without reference and attractors without inherited words.


### Process Precedes Substrate

The active process historically exists before the persistent substrate it later
depends on. This supports designing for active LLM use first, then letting the
substrate format stabilize under the model's constraint profile.


### MNFL Constraint-to-Structure Mapping

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


### Cross-Layer Interface Versus Native Format

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


### Language as Side Effect

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


### Names and Standardization

- Standardization, dictionaries, schooling, and repair norms are "institutional
  repair enzymes" for human language.
- The AI analogue may include conventions, schemas, READMEs, tests, validators,
  trust files, archive indexes, and consumer-written reputation.


## Appendix C. LLM Constraint Profile and Reader Details


### Reader Constraint

The same kind of machinery should write and read the recursively accumulating
substrate. If an LLM writes rigid scripts that are then only read by a Python
interpreter, the model-reader feedback loop weakens. Tools are fine when the
model chooses and interprets their use; rigid workflow scripts can bypass the
cognitive layer.


### Cross-Layer Native Formats

Each recursive layer operates on outputs of the previous layer but develops a
native representational format suited to its own constraints. LLM-native process
language need not look like human narrative text. It may become denser, more
indexed, and more reconstruction-oriented.


### Token-Bound Failure Modes

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


### Human Development and LLM RL Equivalents

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


### Layered Emergence and Comparative Status

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


### The Big Four as Layer-Specific Machinery

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


### Fidelity Scope and Human CoT Before Writing

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


### Reader Constraint Details

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


## Appendix D. Extended Architecture Notes


### Hereditary Ecology Core Mapping

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
- tasks, resource limits, and context limits: ecology

The AI seed is not DNA. It is closer to apprenticeship notes, lab notebooks,
oral tradition, a monastery rule, a research group's inherited style, a startup
playbook, or local operating doctrine.


### Fixed Constructor and Mutable Culture

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


### Primitive Physics and Evolved Filters

The system should not hand-code a mature culture. If every trust rule, archive
filter, reputation mechanism, artifact format, evaluator convention, role, and
review practice is specified in advance, then the result is a human-designed
institution rather than an evolving process culture. But the opposite extreme
also fails. If nothing is fixed, agents can drift, self-certify, preserve
useless artifacts, or redefine success.

The useful distinction is between primitive physics and cultural filters.
Primitive physics should be fixed or slow-changing. Cultural filters should
evolve.

Primitive physics includes:

- fresh episode starts
- bounded context
- bounded seed size
- bounded archive retrieval
- compute, tool use, and attention costs
- current-run scoring that the current run cannot rewrite
- artifact effects that matter only through future reconstruction or use
- lineage continuation and artifact visibility tied to downstream consequence

These are the artificial equivalents of scarcity, mortality, locality,
attention limits, and physical consequence. They are not the final culture.
They are the conditions under which culture must regulate itself.

Above this layer, the system should allow evolving filters:

- trust rules
- provenance norms
- deprecation procedures
- archive conventions
- review practices
- curator roles
- dependency policies
- citation systems
- warning formats
- evaluator-building traditions
- problem taxonomies
- seed-writing conventions

The compact rule is: fix consequence, not doctrine. The constitution should
mostly create the channel through which filters can be proposed, inherited,
tested, and discarded.


### Transmission, Storage, Carryover, Seed, and Archive

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


### Compaction as Transmission Bottleneck

Compaction is not only a context-management trick. It is the hereditary
mechanism that turns a messy rollout into a bounded continuation object.

The basic transition is:

workspace / lifetime trace -> compaction -> lineage seed or carried-forward
artifact -> fresh descendant reconstruction.

The workspace is too noisy to inherit wholesale. A single note is usually too
compressed. A useful seed sits between these extremes: enough structure to let a
fresh child reconstruct useful process, not enough structure to avoid
compression pressure.

This makes seed-writing itself evolvable. A good seed is not a transcript. It
is a compact process packet that tells descendants:

- what to attend to
- what to ignore
- what worked
- what failed
- which tools matter
- which archive pointers are trusted
- which warnings are live
- which assumptions are fragile
- which mutations are promising
- how to allocate scarce effort

Therefore the system is not selecting only for better answers. It is selecting
for better ways of compressing a lifetime into a descendant-operable form.
Ordinary compaction asks what should survive so the next session can continue.
Evolutionary compaction asks which compressed seeds produce better descendants
over many generations.


### Architecture Evolution

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


### Ecology, Competition, and Engineered Drives

Open-endedness tends to require dynamic landscapes, parasites or exploiters,
resource structure, differential continuation, scarce attention, costly
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


### Process Manifold and Policy-Level Heredity

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
- resource allocation
- adaptation rules
- stopping conditions
- archive retrieval policies


### Representation Freedom and Protocol

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


### Two Inheritance-Channel Metrics

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


### Measuring Fitness

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
- explicit costs for archive usage
- dependency formation
- consumer-written validation

Producer-written claims can provide provenance and local notes, but durable
public reputation should come mainly from downstream consumers.


### Archive Visibility, Uptake, and Producer Credit

In the archive channel, artifact fitness is future visibility under validated
uptake. The analog of reproduction is not biological offspring. It is future
influence: retrieval probability, recommendation prominence, dependency status,
inclusion in seeds, adaptation into new versions, and survival through
deprecation pressure.

The archive should distinguish exposure, attention, and uptake.

- Exposure: the artifact was available.
- Attention: a later run inspected or read it.
- Uptake: a later run incorporated, copied, adapted, executed, depended on, or
  carried it forward in a way associated with success.

Only uptake should strongly affect artifact fitness. Search hits, brief reads,
and producer claims are weak signals. A practical first rule is that an artifact
counts as adopted only if it is carried into a child seed, copied or modified
into a derivative artifact, imported as a dependency, used by an evaluator or
workflow, or nominated by a downstream consumer with evidence.

This avoids over-designing causal attribution. Natural selection does not know
perfect causal credit; it uses repeated consequence. The archive can start with
noisy but grounded association:

- Artifacts carried forward by successful unrelated lineages gain visibility.
- Artifacts carried forward by failing lineages lose visibility.
- Artifacts marked misleading by consumers decay.
- Artifacts that are only exposed or mentioned do not gain much standing.

Producer credit should be a later institution, not the primitive mechanism.
Directly rewarding producers invites archive spam, self-promotion, inflated
claims, and artifacts optimized for nomination rather than use. The safer early
rule is: artifacts compete for visibility; lineages compete for descendants.
Only after the archive contains enough downstream consumer evidence should
lineage reputation for producing useful artifacts become a stronger prior.


### Git Ecology Mechanics

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


### Two Views of Cultural Evolution

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

From the artifact-centered view, vertical and cross inheritance are not
fundamentally different kinds of reproduction. Both are cases where a future
interpreter reconstructs, modifies, trusts, depends on, or preserves a
structure across a transmission gap. The agent-centered distinction remains
useful because it asks who inherits from whom, but the artifact-centered
question is whether the structure survives local tradition or foreign
interpretation with enough usefulness to remain causally active.


### What Is Under Differential Pressure

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


### Cross-Inheritance Filters

Cross-inheritance without filters becomes memetic pollution. Filters are needed
because integration is costly, failure is asymmetric, benefit is uncertain, and
downstream consequences can be large.

Possible AI filters:

- retrieval limits
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


### Bounded Attention as Root Scarcity

Bounded attention, bounded context, and bounded compute are the primitive
scarcities that make cultural filters necessary. The relevant compute is
agentic compute: what a rollout can read, inspect, test, reason through, carry
forward, or afford to ignore.

In a large repository, storage is cheap but visibility is scarce. A file can
physically persist forever and still be culturally dead if no future agent reads
it, trusts it, reconstructs from it, or depends on it.

This creates the first meta-problem: given limited context and compute, what
should the agent attend to? A bad lineage wastes attention on stale notes,
misleading artifacts, verbose seeds, irrelevant tools, and low-value archive
branches. A good lineage evolves attention policy:

- read failure evidence before success stories
- prefer artifacts with downstream consumer evidence
- distrust producer self-praise
- run cheap tests before expensive search
- preserve warnings shorter than procedures
- summarize tools by interface and failure mode
- keep archive pointers only if they changed behavior
- distinguish "mentioned" from "used"

The seed is therefore not merely memory. It is an evolving attention-control
object. It tells descendants what to read first, what to ignore, what is stale,
what failed, what changed behavior, what to test before trusting, and how to
allocate scarce effort. Vertical inheritance becomes selection over ways of
allocating bounded cognition.


### Vertical Competition and Delayed Reproductive Value

Vertical inheritance has force only if continuation slots are scarce. If every seed continues equally, bad doctrine, bloated
seeds, stale warnings, fake artifacts, and poor attention policies all persist.
The system becomes accumulation rather than heredity.

Vertical competition can decide:

- which lineages receive child rollouts
- which child seed replaces or forks a parent seed
- which branches are pruned
- which lineages receive more compute or archive access
- which unusual lineages are preserved for exploration

This should not be winner-take-all. One child opportunity per active rollout can
be combined with bootstrap refill so unusual approaches remain possible while
lineages that do not construct successors can disappear.

Immediate viability and delayed reproductive value should be separated.
Immediate score asks whether a child is viable enough to continue: task
success, partial progress, compute cost, bounded seed quality, evidence, and
absence of obvious bloat. Delayed score asks whether that child was a good
ancestor. That can only be known after descendants attempt to reconstruct and
continue from its seed.

A practical loop is:

1. A parent lineage spawns several children.
2. Each child attempts tasks and writes a candidate next seed.
3. Top children by immediate viability enter probation.
4. Probation seeds receive limited descendant slots.
5. Descendant performance updates the reproductive credit of the seed.
6. Seeds whose descendants keep doing well receive more future opportunities.
7. Seeds whose descendants fail, bloat, or stagnate are pruned.

This also explains why lineages leave good seeds. A prompt can request useful
handoff notes, but without reproductive consequence that often becomes ritual
documentation. A lineage leaves better seeds when better seeds produce better
descendants, and better descendants receive more continuation.


### Minimal Selection Loop

A minimal ecology can be described as two coupled selection loops.

Vertical lineage loop:

1. A parent lineage has a seed.
2. Several children start fresh from that seed plus selected archive context.
3. Each child works in an ephemeral workspace under bounded compute and context.
4. Each child attempts tasks and writes a candidate next seed.
5. Immediate viability selects which seeds enter probation.
6. Descendants from probationary seeds reveal reproductive value.
7. Lineages with better descendant outcomes receive more future opportunities.

Archive artifact loop:

1. Rollouts produce local artifacts.
2. Some artifacts are nominated or copied into public archive space.
3. Future lineages receive small archive samples.
4. Some archive artifacts are adopted into code, seeds, dependencies, or
   workflows.
5. Artifacts adopted by successful consumers gain visibility.
6. Artifacts adopted by failing consumers lose visibility.
7. Artifacts ignored, stale, or warned against decay.
8. High-visibility artifacts become more likely to shape future rollouts.

Together, seeds preserve lineage depth, archive artifacts spread portable
structure, rollouts act as temporary phenotypic episodes, and bounded attention
creates selection pressure.


### Minimal Practical System Picture

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


### Practical First Implementation

A first implementation should preserve the heredity structure without trying to
solve every institutional problem at once.

Start with:

- fixed base model and scaffold
- fixed task interface
- bounded seed
- bounded archive retrieval
- ephemeral workspace
- lineage ids
- artifact ids
- immediate task verifier
- simple child selection
- simple artifact visibility update

Do not start with:

- elaborate reputation markets
- complex producer credit
- fully specified skill syntax
- hand-designed archive bureaucracy
- perfect causal attribution
- large institutional role systems

One concrete starter regime is a small active population of lineages. Each
rollout can construct one successor, and bootstrap refill preserves novelty
where no successor is produced. Each child writes a
bounded `next_seed.md`; full workspaces are discarded; seed quality is judged
mainly by descendant performance rather than immediate aesthetics.

Archive artifacts should have ids, producer lineage, and versions. Retrieval is
bounded. Artifacts gain visibility when carried forward by successful unrelated
lineages, lose visibility when carried by failing lineages or warned against,
and should not initially grant strong producer reward. Public prominence belongs
to artifacts, not self-described authors.

Each run receives a task, a seed, and a small archive slice. It may write
arbitrary workspace files, but it must record what it carried forward. Only
carried-forward artifacts count as strong uptake; weak inspection signals can be
logged without being heavily rewarded.


### Four-Layer Architecture and Optional Ephemeral Signaling

The durable architecture has constitution, workspace, lineage seed, and archive.
For multi-agent ecologies, one more channel matters: an ephemeral shared
workspace for live inter-agent signaling.

For multi-agent variants, four writable cultural surfaces are:

- Private workspace: individual lifetime cognition. It is fully writable and
  deleted after the rollout unless compacted.
- Shared live workspace: temporary public traces visible to currently active
  agents. Files vanish when the writer ends or the epoch closes.
- Lineage seed: private vertical culture written for descendants and selected
  by descendant-operable continuity.
- Archive: durable public culture shared across lineages and selected by
  successful downstream uptake.

The shared live workspace is not a second archive. It is a temporary field in
which active rollouts can alter one another's local selection environment. It
might contain failed attempts, partial results, warnings, work-in-progress
claims, cheap test results, candidate tools, observed artifact failures, or
requests for missing evaluators.

The system should not hardcode a full social ontology such as REQUEST, OFFER,
WARNING, REVIEW, BID, and PATCH at the start. Those are already cultural
institutions. A cleaner primitive is that agents may write files into a shared
temporary workspace and other active agents may read them under bounded
attention.

Persistence should not attach to the signal itself. Persistence should depend
on uptake:

1. Agent A writes trace T into shared space.
2. Agent B reads T while A is alive.
3. B uses, copies, tests, or reacts to T.
4. A ends and T disappears.
5. Only consequences that B carries into seed, archive, or behavior persist.

The compact rule is: signals die by default; only consequences reproduce. This
adds a live social layer without making cheap talk directly heritable.


### Differential Persistence and Consequence

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


### Consequence and Moving Targets

The phrase "moving target" hides two different mechanisms. A bad moving target
is metric capture: the agent edits the verifier for its current task, changes
its own score, redefines success after acting, promotes its own artifacts
without downstream uptake, or alters the rules that judge its own continuation.
This should be blocked by primitive physics.

A good moving target is ecological complexification. Successful artifacts
change the future archive, tools become dependencies, old solutions create
maintenance burdens, archive crowding creates retrieval and trust problems,
lineages specialize, successful methods create harder variants, recombination
creates new problem classes, and dependency formation creates versioning and
compatibility pressure.

The top-level continuation filter can remain simple while the world it operates
on becomes more complex. A good artifact should not merely solve a past task. It
should become part of the future environment: something to reuse, distrust,
maintain, compose with, route around, or use to attempt new problems. That is
the difference between a memory system and a cultural ecology.


### Option Value Rather Than Complexity

The system should not select for complexity itself. Complexity can accumulate as
bloated seeds, ritual reports, stale procedures, brittle dependencies,
ungrounded jargon, archive spam, evaluator overfitting, or bureaucracy. Human
culture also accumulates useless complexity.

The useful target is future option value: persistent ability to create,
preserve, recombine, and select better future options under scarce attention and
changing constraints.

Valuable inherited structures are often answer-producing machinery rather than
object-level answers. Human examples include counting, maps, measurement,
writing, law, markets, mathematics, experimental method, engineering standards,
libraries, schools, software, and institutions. AI analogues include
evaluators, test generators, problem taxonomies, tool interfaces, failure
libraries, repair procedures, retrieval policies, dependency maps, trust
markers, process compression, deprecation norms, and archive navigation aids.

A useful metric asks whether inherited structure increased future option value.
Approximations include transfer to perturbed tasks, lower search cost, improved
descendant performance, successful cross-lineage adoption, better failure
recovery, reduced archive confusion, improved ability to evaluate future
artifacts, and creation of new productive problem classes.

Complexification is not the goal. Reusable constraint-management is the goal.


### Operational Failure Modes and Counterpressures

Several failure modes should be treated as central design tests.

Seed bloat: seeds become long, vague, and expensive to reconstruct.
Counterpressures include seed size limits, descendant performance, context-cost
penalties, and compression pressure.

Ritual documentation: agents write reports because prompted, but descendants do
not use them. Counterpressures include scoring only descendant-operable seeds
and giving little value to self-report without later uptake.

Archive spam: lineages flood the archive with artifacts. Counterpressures
include stricter archive admission than seed continuation, visibility based on
consumer adoption, and no direct reward for producing artifacts.

Producer self-promotion: lineages claim broad usefulness without evidence.
Counterpressures include consumer-written uptake and treating producer claims as
weak provenance rather than reputation.

Popular but brittle artifacts: artifacts spread because they are easy to
understand, not because they are robust. Counterpressures include downstream
performance correction, decay under failure, and perturbation tests for
high-visibility artifacts.

Stagnant old lineages: long-lived lineages monopolize resources without
improving. Counterpressures include age discounting, recent-performance
weighting, stagnation penalties, and exploration capacity for young lineages.

Shallow novelty: cross-lineage borrowing creates many variants but little depth.
Counterpressures include vertical continuity, descendant viability, and
multigeneration lineage tracking.

Narrow depth: vertical lineages become powerful but isolated. Counterpressures
include archive sampling, portability pressure, and cross-lineage adoption.

Metric capture: agents alter what counts as success. Counterpressures include
uneditable current-run scoring, delayed validation for evaluator changes, and
slow externally compared constitutional changes.

Static benchmark plateau: the system optimizes a fixed task distribution
without creating new gradients. Counterpressures include task variation, archive
consequences, dependency formation, shifting problem pools, and maintenance
burdens created by prior success.


### The Complexification Gap

The architecture above supplies the structural components for artificial
cultural evolution: fixed constructor, ephemeral workspace, vertical seed,
public archive, bounded attention, and selection mechanisms. Those components
are necessary, but they do not yet explain self-complexification. With fixed task
difficulty and uniform continuation rights, the system can converge. The archive
may grow, but it remains optional memory rather than an environment that later
agents must inhabit.

Uniform continuation is especially weak. If every rollout that crosses a task
threshold receives the same number of descendants, then efficiency, compression,
reuse, and artifact production are only weakly selected. The system still has a
binary success filter, but it lacks a mechanism by which better conversion of
scarce resources becomes more future search.

Biology and culture complexify because prior success changes later selection
conditions. Cyanobacteria altered the atmosphere; agriculture produced surplus;
surplus enabled cities; cities created coordination, maintenance, and governance
problems. The analogue in an artificial system is not reward for complexity
itself. It is that successful artifacts become future dependencies, navigation
problems, compatibility constraints, trust targets, and maintenance burdens.

This endogenous pressure must remain tethered to exogenous ground. Generated
complexity can easily become ritual, spam, overfitting, or bureaucracy. A useful
dependency chain ultimately reaches externally evaluated consequences: better
task performance, lower cost, greater robustness, improved recovery, or an
expanded class of solvable tasks. If the chain to grounded consequence breaks,
the accumulated structure should lose continuation value.


### Rollout-Owned Continuation as Minimal Selection

One reserved next-generation opportunity per rollout makes successor
construction consequential independently for each source. A lineage continues
from that rollout only if it produces a usable handoff. Every configured
population position without a spawned child is repopulated from a stable bootstrap seed,
which prevents a weak generation from permanently collapsing exploration.

This continuation rule alone is not open-ended ecology. It becomes ecological
only when successful artifacts alter future conditions by becoming dependencies,
shortcuts, standards, risks, interfaces, or maintenance obligations for later
agents.


### Interaction Primitives

The system should expose primitive interactions, not a mature social ontology.
Agents may read public artifacts, copy or fork them, cite dependencies, publish
counterevidence, and propose patches. Direct in-place modification of another lineage's artifact should be
controlled by provenance and validation; otherwise the archive becomes writable
noise rather than a selective substrate.

These primitives make trade-like, predation-like, parasitic, symbiotic, and
institutional dynamics possible without coding those categories as initial
roles. The interaction space is designed. The interaction rules are allowed to
stabilize only if they help descendants operate under scarcity.

A conservative first implementation can measure delayed creator value when
independent descendants use an artifact and measurably improve score, cost,
robustness, or task reach, without adding an exchange currency.


### Emergent Ecology

An inheritance system becomes an ecology when artifacts form load-bearing layers. A
tool saves search for a strategy. A strategy makes an index useful. An index
makes conventions valuable. Conventions lower integration cost and make more
complex tools usable. The point is not a designed hierarchy, but a dependency
structure in which higher layers save scarce effort while remaining answerable
to grounded tasks.

A possible layering is:

- base tasks and verifiers as exogenous ground;
- tools and examples that reduce direct solution cost;
- strategies and repair procedures that reduce search cost;
- indexes and trust markers that reduce retrieval cost;
- conventions and interfaces that reduce composition cost.

Specialization becomes viable when producing useful artifacts and using useful
artifacts are both routes to continuation. Some lineages may become tool
builders, others integrators, others auditors, others problem explorers. Those
roles should remain provisional. They persist only if they improve descendant
performance under token, context, and attention limits.

The death mechanism matters. Lineages that run out of continuation capacity
cannot spawn rollouts. Artifacts that stop saving cost, improving robustness, or
expanding reachable tasks should lose visibility. Without starvation and decay,
the system accumulates junk faster than it accumulates culture.


### Real-World Correspondence

This setup is a simplified model of real LLM use. Model calls consume real
resources; successful workflows create value; useful tools, prompts,
APIs, and procedures spread; inefficient teams shrink; open-source artifacts are
forked; internal tools become dependencies; platforms create ecosystems.

The mapping is not proof. It is a design check. If the architecture cannot
model the simplified economy already surrounding LLMs, it is unlikely to support
open-ended artificial culture. The target is not to prebuild contracts,
reputation systems, markets, or institutions. It is to provide primitive
resource, inheritance, and interaction conditions under which useful versions of
those structures can appear if they solve real continuation problems.


### Core Summary

- Base LLM: stable cognitive architecture.
- Constitution: regenerated drives and social motives.
- Lineage seed: vertical inherited culture.
- Git archive: public cross-lineage culture.
- Workspace: individual life.
- Rollout: temporary phenotype/interactor.
- Tasks and rollout-owned child opportunities: ecology and differential continuation.
- Interaction primitives: read, copy, fork, cite, and patch.
- Selection: differential continuation, uptake, trust, reuse, dependency, and
  cost-sensitive future option value.
- Compaction: the transmission bottleneck that turns a rollout into a bounded
  seed or carried artifact.
- Bounded attention: the root scarcity that makes filters, indexes, trust, and
  seed discipline necessary.
- Archive visibility: artifact fitness expressed as future influence under
  validated uptake.

The private seed is not DNA. It is vertically transmitted culture. Git is not
automatically an ecology. It becomes one when artifacts compete for scarce
attention, trust, context, dependency, validation, execution cost, and downstream
use.

The agent-centered view asks which lineages continue. The artifact-centered view
asks which artifacts keep getting reconstructed. Both are required because
agents and artifacts reproduce each other.

The design principle is fixed primitive consequence, explicit continuation,
evolvable cultural filters, two inheritance channels, delayed selection, and
artifact visibility through successful adoption. Do not select for complexity
itself. Select for future option value under bounded attention, finite slots,
and changing constraints.


## Appendix E. Operational Substrate and Optional Training Variants


### Operational Substrate

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


### Optional Training and Execution Variants

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


### Optional Cycle Boundary Details

- The cycle boundary can be tied to writing. Write functions like a stop codon:
  after the model writes a patch or artifact, context wipes and the next cycle
  reads the updated repository state.
- The model can choose actual cycle length within an infrastructure-imposed
  maximum by deciding when to write.
- The target maximum cycle length is an open parameter: too short prevents
  coherent work; too long lets the model solve without externalizing state.

These cycle boundaries are an optional training-oriented implementation detail.


### Optional Parallel Training Details

- Generation remains sequential because each repository state depends on prior
  patches.
- Training can still be parallelized because, after context wipe, every cycle is
  conditionally independent given its repository state.
- Variable-length rollouts produce different numbers of training samples. A
  successful longer rollout trains more cycle decisions, which may be correct if
  many decisions contributed to success.


### Optional Universal Probabilistic Turing Machine Framing

- The machine is framed as a universal probabilistic Turing machine with stored
  programs: deterministic execution and stochastic model proposal both operate
  over the same self-referential repository.
- The point is mathematical consistency. Recursive improvement requires both
  transition functions over a substrate that can store the programs,
  instructions, tests, and regulatory documents that affect future transitions.


### Weight Consolidation Analogy

- RLVR/GRPO already has variation, selection, and partial retention.
- Improvements can compile into weights as habits, sometimes aided by curated
  replay buffers.
- This resembles organism- or behavior-level selection more than gene/word-level
  evolution because inherited subparts do not persist as discrete lineages.


### Part-Level Selection in the Repository

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


### Archive Death by Invisibility

- Unused repository artifacts resemble pseudogenes or obsolete
  dictionary words: they may remain physically stored but no longer get
  transcribed/read.
- The failure mode is not storage bloat alone; it is loss of visibility and
  navigability under bounded reading.


### Storage Fidelity and Operational Constraints

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


## Appendix F. Experiment Ledger and Problem-Pool Details


### Why Module Systems Plateau

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


### Experimental Implications

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


### Predictions and Failure Modes

The framework makes several predictions.

If context is too large or tasks are too easy, external process artifacts will
remain optional and weakly selected.

If the system stores everything without retrieval limits, archive quality will
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

If tasks are solvable without artifacts under bounded context, the ecology
will plateau at direct task solving without specialization.

If rollout-owned continuation is present, lineages that create useful handoffs
should persist more reliably across generations.

If interaction primitives are available, transfer dynamics such as trade,
predation-like capture, parasitism, and symbiosis should become possible and
measurable rather than being predefined as roles.


### Experiment Ledger

The negative results constrain the theory. Follow-up experiments should clarify
which failure modes are structural and which are implementation-specific.
#### Persistent Canvas Substrate

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
#### Dynamic Module Injection Dataset

Hypothesis:

If previously successful traces or modules are injected into bounded new prompts,
the model will increasingly adopt reusable fixed structure instead
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
#### Module Extraction from Successful Traces, Random Injection

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
#### Module Extraction plus Ranked Injection

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
- Slightly higher mean token use than random insertion, unexpectedly.

Interpretation:

Ranking did not solve causal attribution. Injection prominence did not imply
useful process dependence.
#### Usage-Based Module Scoring

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
- Slightly higher token use than random insertion.

Interpretation:

Usage rate alone is too weak and too indirect. It does not guarantee causal
application or downstream value.
#### Module Analytics and Summarization

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
#### Selection-Shaped Compositional Vocabulary

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
#### Usage-Weighted Filtered Injection

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
#### Workspace Write-Triggered Context Reset

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


### Practical Problem-Pool Experiment Details

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


## Appendix G. Current AI R&D and Contemporary Systems


*Placement note:* this material is background and limiting-case analysis, not the emotional center of the paper.


### Field Landscape Details

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


### AI-Assisted R&D as a Hybrid Cultural System

Current frontier-AI development already contains elements of the proposed
pattern. Models can generate candidate training ideas, code patches, synthetic
data, evals, curricula, debugging strategies, or infrastructure improvements.
Labs then test some of these candidates, preserve successful changes, and
incorporate them into later systems.

This is a genuine cumulative loop, but the unit of accumulation is not the model
alone. It is a hybrid system: model, humans, datasets, codebase, evals, compute,
institutional judgment, and training pipeline. Humans remain load-bearing as
selectors. They decide which proposals are worth testing, which evals matter,
which failures are meaningful, which gains are real, and what "better" means.

Therefore, reducing human labor inside the loop does not automatically remove
human selection. Automating code writing, experiment execution, data generation,
or report production reduces the cost of variation and testing. It does not by
itself create an autonomous selection ecology. To remove humans as selectors,
the system must replace human judgment with protected, grounded,
system-internal consequence: bounded resources, uneditable current-run scoring,
downstream uptake, lineage continuation, archive decay, and task or environment
feedback.

This paper is not primarily a critique of current labs. Rather, current lab
practice is treated as a partial and human-mediated instance of a broader
structure. The central question is what additional architecture would be needed
for the selection layer itself to become artificial and endogenous.


### Why Training Recipes Are Not Genomes

A successor-model training recipe should not be treated as the AI analogue of
DNA. It is too coarse, distributed, and human-mediated. A frontier training run
depends on datasets, filtering rules, optimizer settings, infrastructure,
evaluation culture, debugging lore, human judgment, hardware constraints, safety
policies, and undocumented institutional practice. It is not a compact
self-reproducing description that is automatically copied and interpreted by a
stable constructor.

This matters because cumulative evolution requires part-level visibility. If
the selectable unit is only "the entire training run worked," then the system
receives weak credit assignment. It may preserve a better model checkpoint, but
it does not necessarily know which process parts caused the improvement.
Accumulation becomes expensive, entangled, and difficult to recombine.

The more relevant units are smaller and more process-like: data filters,
curricula, evals, tool interfaces, training-stability tricks, synthetic-data
generators, debugging procedures, archive indexes, verifier improvements, task
taxonomies, and seed-writing conventions. These are closer to cultural artifacts
than genes. They become heritable only when future runs reconstruct, modify,
depend on, and differentially preserve them.

Weight updates may consolidate discoveries, but they are not the whole recursive
substrate. In the proposed framework, training is one possible consolidation
pathway for process structures discovered by a broader hereditary ecology.


### Evolutionary Baselines and Limits

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
evaluation, retry policy, resource allocation, trace preservation.

The deeper bottleneck is fixed ecology, not fixed chemistry. Static benchmarks
permit improvement without consequence. Open-endedness requires consequences
that feed back into what later structures must become.


### DGM Cost and Level

- DGM-style search is expensive and organism-level. A specific remembered cost
  signature is about `$22k` per run.
- The point is not the exact cost estimate, but the scaling concern: selecting
  whole agent codebases is expensive and gives weak part-level credit.


### Contemporary Multi-Agent and Inference-Time Systems

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


### Confidence, Reuse, and Grounding

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


## Appendix H. Definitions, Claim Inventory, and Open Threads


### Working Definitions

Transmissible process representation:

A model-readable, reconstructible representation that can carry process-relevant structure across fresh-context gaps.

Language-like process structure:

A transmissible process representation with discrete, compositional, hierarchical, conventional, and self-referential properties. This is broader than ordinary human language and narrower than persistence or storage in general.

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

Shared live workspace:

A temporary public environment visible to currently active rollouts. Its traces
die by default unless another agent carries their consequences into behavior,
seed, or archive.

Lineage seed:

A bounded inherited process packet passed from parent to child. It is vertical
culture, not literal DNA and not a full workspace dump.

Compaction:

The bottleneck that turns a rollout's noisy workspace or lifetime trace into a
bounded seed or carried-forward artifact that descendants can reconstruct from.

Archive:

The shared public cultural store from which unrelated lineages can retrieve,
adapt, validate, and depend on artifacts.

Uptake:

Stronger than exposure or inspection. An artifact is taken up when a later run
copies, adapts, depends on, executes, includes, or carries it forward in a way
associated with downstream success.

Immediate viability:

Whether a rollout solves or improves the current task.

Vertical fitness:

Whether descendants can reconstruct, continue, vary, and preserve useful
process from the inherited seed.

Archive fitness:

Whether unrelated lineages retrieve, adapt, validate, and benefit from a public
artifact.

Primitive physics:

The fixed or slow-changing constraints that make selection possible: fresh
starts, bounded context, bounded inheritance, costly attention, uneditable
current-run scoring, and downstream consequence.

Option value:

The future usefulness of inherited structure for creating, preserving,
recombining, and selecting better options under scarce attention and changing
constraints.

Process language:

The emergent set of compact external conventions, files, references, modules,
tests, maps, and procedures by which fresh LLM episodes reconstruct useful
working state and continue improvement.


### Citation Targets

Citation clusters to develop:

- evolutionary theory and heredity
- cultural evolution and two-channel inheritance
- iterated learning and compositionality
- external memory, writing, and cumulative culture
- self-reference, formal systems, Turing machines, and von Neumann self-reproduction
- RLVR, GRPO, inference-time scaling, and verifier-based reasoning as optional
  training and evaluation variants
- memory-augmented LLM agents and tool-using agents
- Darwin Godel Machine and related evolutionary agent systems
- software repositories, version control, and open-source cultural production


### Thematic Claim Inventory

The Recursion Problem:

- Only two known systems clearly recurse at planetary scale: biology and human
  culture.
- The shared property is self-referential representation: the process can
  encode and modify rules relevant to its own operation.
- Transmissible process representation enables reusable parts; reusable parts enable accumulation.
- Plasticity and persistence cannot be maximized in one substrate, motivating a
  two-loop structure.
- Historically, active process precedes persistent substrate: RNA-like activity
  before DNA, brains before writing.

Conditions for Language-Like Process Representation Emergence:

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

Failure Modes of Token-Bound Systems:

- Sequential bias, context loss, lack of protocol, lack of modular reward, weak
  recovery loops, and global drift.
- Each failure is tied to a missing primitive such as tree/graph structure,
  external memory, schemas, reuse incentives, verifiers, or planning.

LLM Primitives:

- LLMs already show partial primitives: chain-of-thought, in-context learning,
  roles, structured output, and tool schemas.
- Reasoning domains succeed disproportionately because they are verifiable.
- Required universal properties: atomic operations, modularity, protocols,
  feedback, and persistence.

From Childhood to Systems:

- Human cognition progresses through chunks, scripts, composition, named
  routines, interfaces, abstraction, systems, and protocols.
- LLM analogues include atomic operations, mini-modules, interfaces,
  persistence, libraries, and meta-learning.

Emergence, Exploration, and Universal Selection:

- LLMs currently sit between proto-syntax and early discourse.
- Comparative table maps DNA, human language, and LLMs across alphabet, grammar,
  modules, error correction, memory, division of labor, abstraction, and protocol
  growth.
- A selector rewarding communicability and structure may drive protocol
  emergence.

Chain-of-Thought Features:

- CoT is treated as proto-language or pre-literate reasoning trace.
- Markers such as "wait" and "okay" may function as segmentation operators
  rather than ordinary English.

Credit, Superlanguage, and Module Emergence:

- Long credit assignment and persistent named modules interact.
- Partially solving long credit assignment enables superlanguage; superlanguage
  then reduces the burden on raw token-level long credit.
- Biological analogies include RNA brute force, dopamine/replay, and algorithmic
  redistribution.

The Universal Pattern:

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

Scale, Depth, and Demonstration:

- Fields deepen because abstractions and external tools improve, not because
  brains grow.
- If knowledge remains externally representable and tool substrates improve,
  depth may continue without an obvious theoretical ceiling.

Proto-Language and Suppressed Emergence:

- LLM quirks such as confident nonsense, hallucinated citations, drift,
  verbosity, weak commitment tracking, absent dialect or jargon formation,
  schema fragility, and role leakage are predicted signatures of fluent symbol
  manipulation without persistent selection.
- The "big four" primitives are reinterpreted as layer-specific machinery:
  in-context learning, chain-of-thought, role, and structure.
- LLMs have high within-read bandwidth but poor cross-read persistence.

Substrate Separation and Bootstrap Dynamics:

- "External" is functional, not spatial. A substrate is external if it sits
  outside the fast adaptive loop and is writable only through gated selection.
- ICL and canvas are complementary: ICL is fast adaptation, canvas is persistent
  addressable state.
- RLVR/GRPO has variation and selection, but lacks part-level replicators and a
  protected archive under agent control.

Boundaries and Secondary Selection:

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

Secondary Gradients and Convergence:

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

Selection on Process and Experimental Synthesis:

- Successful emergence requires environment, not merely a wall.
- Required ingredients include populations, variation, selection pressure,
  part-level replication, memory substrate, protection and addressability,
  composability, bottlenecks, disequilibrium, generations, and open-endedness.
- Some systems solve narrow walls without compositional explosion.
- Substrate-replicator coevolution often stabilizes before later explosion.
- LLMs may already be a sufficiently strong substrate; missing dynamics may be
  selection on process and transmission.

From Modules to Superlanguage:

- Prior module experiments failed because modules were optional additions to a
  fully capable system.
- Vocabulary emerges from transmission gaps.
- Use and replication must be coupled: in human language, using a word and
  transmitting it are often the same act.

Bottleneck Design:

- General compositional language may not emerge from gradual broadening alone.
- Domain-specific units can stabilize for long periods before a phase
  transition.
- A defensible near-term goal is domain-specific skills that accumulate and
  improve solve rates within a bucket.

The Externalization Ladder:

- Recursive systems shift selection to deeper units: structures, then symbols,
  then processes.
- Selection levels are nested: environments evaluate wholes, wholes determine
  part fitness, parts determine process fitness.
- Credit assignment requires representing a part as an object of evaluation.
- Structures must become persistent, replicable, and variable before selection
  can refine them.

Carrying Cost and Reader Constraint:

- The carrying cost is reconstructing usable state from artifacts, not merely
  storing artifacts.
- Current systems provide pieces of the loop: coding agents, DGM-like systems,
  Live-SWE-agent, MemRL, LAMER.
- Self-referential recursion requires reader and writer to be the same kind of
  machinery.
- Rigid scripts can bypass model cognition and therefore weaken the recursive
  feedback loop.
- Language is a side effect of practical pressure, not the original target.

Training and Execution Variants:

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

Endogenous Ecology Through Inheritance Dynamics:

- Rollout-owned child opportunities make continuation behavior consequential.
- Bootstrap refill preserves exploration without uniform lineage survival.
- Interaction primitives allow exchange without predefining mature institutions.
- Fixed tasks plus explicit continuation are still insufficient unless artifacts
  become load-bearing future conditions.


### Open Theoretical Threads

These threads remain active parts of the research argument.


### Open-Endedness Versus Domain-Specific Accumulation

The minimal vertical/cross-inheritance architecture should not be claimed to
produce full open-endedness by itself. A more defensible short-term target is
domain-specific accumulation of process artifacts that improve solve rates
within a bounded bucket. Broader open-endedness likely requires ecological
consequence, shifting tasks, competition, scarcity, and cross-lineage
recombination.


### Open Questions

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

11. What episode boundary, seed size, and archive retrieval limit best force
    externalization without preventing coherent work?

12. What signs would indicate emergence of a genuine LLM-native process
    representation rather than human-readable bureaucracy?

13. Which experimental failures are caused by weak attribution, which by task
    easiness, and which by the absence of ecology?

14. How should deterministic execution and model interpretation be balanced so
    tools help without bypassing recursive cognitive feedback?

15. What counts as falsification for the near-term version of the theory?

16. What rollout-owned child-opportunity and bootstrap-refill regime creates useful selection
    pressure without preventing exploration?

17. What signs would indicate that emergent transfer dynamics (trade, predation,
    symbiosis) are forming rather than remaining absent?

18. How does the system avoid accumulating complex junk when self-complexification
    begins, and what exogenous grounding mechanisms are most effective?


### Preconditions and Forcing Constraints

Emergent language-like process representation requires a concrete set of design pressures:

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


### Bottleneck Design and Generalization Limits

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

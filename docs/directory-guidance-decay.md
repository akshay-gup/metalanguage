# Directory guidance decay — internals

Moved from the README. Companion to the opt-in flag docs there
(`--directory-agents-mode decay --directory-agents-decay-steps K`).

## Guide injection and the pre-tool gate

  Automatically supplied root and nested guides use
  `<AGENTS_MD path="…/AGENTS.md">` followed by the file contents and
  `</AGENTS_MD>`. The path is the resolved source filename, escaped for the
  quoted attribute. Existing trailing-whitespace trimming is unchanged.

  Before each subsequent tool dispatch, the same loader resolves the tool's
  exact directory or explicit workdir. For shell tools it additionally resolves
  statically executed literal `cd`, `pushd`, and `popd` transitions and literal
  leading `git -C` operands. If any resolved path/content digest is unseen, all
  unseen `<AGENTS_MD path="…/AGENTS.md">` blocks are injected and atomically
  recorded, while the tool is denied before execution with the neutral result
  `Local context activated;
  tool was not executed.` The model receives another inference step and must
  reissue or revise the call; the original call is never resumed automatically.
  A repeat executes normally, and a changed `AGENTS.md` digest gates once again.

  The parser is deliberately bounded rather than a complete Bash parser:
  dynamic targets such as `cd "$dir"`, `cd -`, tilde, command substitutions,
  globs, and `pushd +N` are not inferred. Pipelines, background jobs, subshells,
  functions, and shell control structures are also unsupported. An `&&`/`||`
  branch whose execution depends on an unobserved non-directory command status
  is not followed. Quoted text, comments, and heredoc bodies are not treated as
  commands.

  Literal leading `git -C DIR` operands are treated as directory-scoped work
  even though Git does not change the shell PWD. Repeated operands resolve in
  Git order, each relative to the preceding Git directory; quoted literal and
  absolute paths are accepted, `--` ends global option parsing, and dynamic,
  malformed, or unsupported global-option forms are ignored. Every resulting
  managed directory is considered even when Git later exits unsuccessfully,
  because the attempted Git operation was already scoped there. Multiple
  statically executed Git commands in one ordinary command list are supported;
  branches dependent on an unknown prior status remain deliberately unobserved.
  Each unique path/content digest is injected once, with no
  Metalanguage-specific content-size cap. Only regular, non-symlink, nonblank
  UTF-8 exact-directory files under managed roots are eligible; an empty exact
  file never falls back to an ancestor. State records label `initial`,
  `pre_tool_gate`, and `post_tool_fallback` activations. The retained post-tool
  pass shares that state and remains a fallback when a statically recognizable
  scope (for example, one created earlier in an unconditional command list)
  becomes resolvable only after execution. It does not infer dynamic shell
  values or a final PWD.

  Codex native tools and Code Mode nested tools use the trusted `PreToolUse` and
  `PostToolUse` hooks; the redundant initial `UserPromptSubmit` hook is not
  installed. The managed Codex source forwards an explicitly supplied
  `exec_command.workdir` unchanged alongside `command` before execution and on
  direct completion; an omitted workdir stays omitted. The existing directory
  resolver uses this start directory without inferring a dynamic final PWD.
  Completion through a later `write_stdin` still lacks the original workdir.
  Direct OpenRouter gates at its dispatch boundary.
  OpenCode's generated plugin gates native Bash and other native tools through
  `tool.execute.before`, then retains `tool.execute.after` fallback. Nested
  context is projected through `experimental.chat.messages.transform` as a
  clearly labelled **synthetic user-role message**, not an assistant statement
  or a new human request. This intentionally has lower instruction authority
  than Codex's developer-role additions. The fixed root/system instructions and
  actual initial `Begin.` message remain unchanged; nested guides no longer
  accumulate in the system prefix.

  Each activation gets a unique managed message ID. At the first message
  projection after activation, it is anchored after the last whole conversation
  message, following that exchange's tool calls/results and before the model
  reconsiders the denied call. Later projections retain that anchor and ID,
  rather than moving the guide to the tail. Callback batches retain arrival
  order; pre-gates and post-fallbacks share a serial queue. A new fallback also
  latches subsequent admissions until its context is projected; already
  dispatched tools are not undone. A late callback first appears at the next
  available projection, without retroactively changing an earlier request.
  System transforms alone cannot release the pre-tool latch.

  This is a request projection held by the plugin for the live session, not a
  persisted user message in OpenCode's database or a rewritten tool result.
  The host's path/digest activation ledger remains the delivery audit. Repeated
  projections/duplicate callback bodies do not duplicate owned messages; changed
  guide revisions remain cumulative at their separate activation positions.
  Only owned IDs are managed: copied guide text in real user/assistant messages
  and tool outputs is untouched. Pending tool results or a missing historical
  anchor stop projection rather than silently relocating guidance. Automatic
  compaction/pruning is disabled by the worker; restoring this in-memory
  projection after a server restart or resuming that native session is not
  supported. New managed rollouts create a new native session. OpenCode decay
  remains unsupported. This placement change and its focused regression tests
  have not been run or live-validated. The previously observed installed
  OpenCode 1.18.31 remains outside the audited 1.18.29 whitelist; that separate
  live-validation blocker is unchanged.

  OpenCode 1.18.29 Code Mode
  exposes only MCP calls inside its confined program, not native Bash; those
  nested MCP calls do traverse the same plugin callbacks, while there is no
  Code Mode native-shell boundary to intercept.

## Decay mechanics

Root guidance remains fixed. A nested exact-directory guide activated after
acknowledged model step `s` is eligible for steps `s+1` through `s+K`.
Codex supplies its `<AGENTS_MD path="…/AGENTS.md">` block as developer
context. Patched OpenCode inserts a labeled synthetic USER message after the
original conversation anchor, preserving chronological placement. It is
excluded before step `s+K+1` unless an observed access renews it. For example,
K=1 activation after step 1 makes the
guide available in step 2; an access in step 2 renews it through step 3. This
example does not select a default K. Multiple tools within one model inference
do not advance age. A and B can coexist; changing directory does not evict A.
Renewal changes only the deadline, retaining the original message position.
Digest revision replaces that managed version with a new tail activation.
Expired reentry activates again even if that path/digest was historically seen.

New/revised pre-tool activations deny the call with the existing neutral result
and require a new inference and explicit reissue. Further tool admissions from
that originating inference remain blocked, including CodeMode catch/retry and
late calls from older cells. Independent scopes observed during the same
inference can still accumulate, avoiding A/B eviction oscillation. Expiry itself
happens at a new request boundary, where the model receives the reduced input;
it does not need an additional removal-only tool deferral. Already admitted or
running operations may finish: this does not roll back a dynamic program's prior
effects. Post-tool fallback has the same lifetime; late fallback from an older
inference is ignored. The existing delayed `write_stdin` workdir limitation
still applies.

The same parser and file checks resolve accesses. Only successfully read,
nonblank eligible guides renew. Missing, empty, unreadable, unsafe and unresolved
files leave an existing deadline unchanged; they do not trigger immediate
eviction or renewal. Unknown dynamic targets do not renew guessed scopes.
A known explicit start directory can renew even if a later dynamic transition
is unknown. No ancestor fallback or content-size cap is introduced. Access
means resolver observation, not demonstrated semantic uptake by the model.

Each Codex logical sampling step counts once on `response.created`. The patched
OpenCode AI SDK path waits for provider response metadata before releasing any
model output to the SDK's tool executor; a stable assistant message ID identifies
the request. Transport retries before metadata reuse that ID and snapshot.
OpenCode refuses a second provider submission under an ID that has already
acknowledged, so a later stream failure stops that rollout instead of silently
undercounting a retry. A failure/cancellation before acknowledgement consumes no
step; after acknowledgement it consumes one even if generation fails later.
Provider acceptance with a lost acknowledgement is unknowable and conservatively
does not count. Codex prewarm and OpenCode auxiliary title generation are outside
the managed sampling ledger. Atomic request snapshots wait for earlier activations;
old inference admissions cannot reopen a closed gate.

Only native-owned message IDs are filtered from sampling requests. Unrelated
developer instructions, assistant reasoning/messages, tool outputs, quoted
copies and files remain unchanged. The audit history retains original messages;
there is no claim of clean forgetting or reversal of propagated information.
Codex's existing WebSocket prefix check rejects continuation after removal and
sends the full current input without `previous_response_id`; no session reset
or proxy is used. Patched OpenCode requires the OpenAI or OpenAI-compatible
AI SDK stream to supply a nonempty provider response ID; other runtime/provider
paths fail closed. It disables the OpenAI WebSocket continuation path and rejects
opaque previous-response or conversation references, then replays the filtered
input. Manual task calls without an acknowledged inference identity also fail
closed. Compaction has a managed inference ID and may stop when selection has
removed an active guide's original anchor. Actual request tokens can decrease,
but retained audit/history size and conservative local context-boundary
estimates need not decrease.
The managed PreCompact stop policy remains in force; this does not add resumable
native-session leases or permit replaying an audit transcript as a decay session.

The Codex host control directory and patched OpenCode private worker state
root each receive `directory_agents_decay.jsonl`: request
snapshots identify excluded/retained managed IDs, accesses record path/digest,
deadline and gate status, and acknowledgements identify retries. Prepared and
committed access records distinguish interrupted publication. Log writes fail
closed; no guide bodies are duplicated into this lifecycle log. Resolver failure
also fails closed before dispatch. Live lease state is session-local; a process
restart must start a new rollout, and existing native-session resume rejection
is unchanged. The cumulative seen ledger remains separate from active leases.


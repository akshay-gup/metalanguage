# OpenCode backend — reference

Moved from the README. Companion to the quickstart and flag list there.

## Sandbox and containment

The default Linux launcher uses bubblewrap with a private PID namespace,
only the runtime binaries and fixed MCP socket proxy mounted read-only, explicit
writable rollout/archive/shared roots, a private `/tmp`, and parent-death
cleanup. Linux, readable procfs, PID namespaces, and a working bubblewrap launch
are preflight requirements and fail closed. The Python lineage callback runs
outside the rollout sandbox behind a random authenticated loopback endpoint;
its command, context, logs, and spawn-slot state are not mounted into the
OpenCode server. Callback crashes, malformed replies, and
timeouts return structured retryable tool results over HTTP 200 so the same
parent can retry and continue. Benchmark modes fail closed if bubblewrap is disabled. Network remains
explicitly enabled because the private HTTP server
boundary and provider calls cannot currently operate in a separate network
namespace; `--opencode-network-mode none` therefore fails closed. The
`unsafe-none` mode is rejected because rollout containment requires bubblewrap.

The audited OpenCode API reports MCP connection status but does not enumerate
MCP tool IDs. The runner validates required connectivity and fails closed on
empty/invalid allowlists; unlisted tools are denied at execution time. For an
evaluated benchmark, every stdio benchmark server runs as a worker-supervised
host process outside the model bubblewrap. OpenCode can reach it only through a
single-use, per-rollout, mode-0600 Unix-socket capability and a fixed read-only
stdio proxy. The socket exposes only the exact MCP protocol; no benchmark
context, task store, event log, ARC state root, host command, bearer credential,
or writable benchmark root is mounted in the model sandbox. SuperGPQA and ARC
retain their native MCP names, schemas, immediate scoring, timeouts, resources,
and image-attachment path.


## Custom providers

The native worker supports a narrow form of the official OpenCode
[custom-provider configuration](https://opencode.ai/docs/providers/#custom-provider)
for generic OpenAI-compatible endpoints. The provider portion of `--model`
must equal `--opencode-custom-provider-id`. The audited package allowlist is
`@ai-sdk/openai-compatible` for `/v1/chat/completions` and `@ai-sdk/openai` for
`/v1/responses`. Both packages are bundled by pinned OpenCode `1.18.29`, so the
worker never installs provider packages at runtime; any other package fails
before launch.

A complete custom configuration requires provider ID, display name, package,
base URL, and an API-key environment-variable name. Optional headers use
repeatable `--opencode-custom-provider-header-env HEADER=ENV_VAR`; literal key
or header values are not accepted. Context and output limits are optional but
must be supplied together. Plain HTTP is accepted only for loopback endpoints;
non-loopback endpoints require HTTPS.

The private config emits the documented `provider.<id>.npm`, `name`, `models`,
`options.baseURL`, `options.apiKey: "{env:VAR}"`, `options.headers`, and
per-model `limit.context`/`limit.output` fields.

For example:

```bash
export MY_PROVIDER_API_KEY='replace-me'
export MY_PROVIDER_TENANT='replace-me'
python3 main_loop.py \
  --worker-backend opencode \
  --model local-ai/my-model \
  --opencode-custom-provider-id local-ai \
  --opencode-custom-provider-name 'Local AI' \
  --opencode-custom-provider-npm @ai-sdk/openai-compatible \
  --opencode-custom-provider-base-url http://127.0.0.1:8000/v1 \
  --opencode-custom-provider-api-key-env MY_PROVIDER_API_KEY \
  --opencode-custom-provider-header-env X-Tenant=MY_PROVIDER_TENANT \
  --opencode-custom-provider-context-limit 32768 \
  --opencode-custom-provider-output-limit 4096
```

Only environment-variable names and other nonsecret settings enter the private
disposable config and run metadata. Secret values travel through the existing
allowlisted environment/fingerprint pipeline; run records contain their
aggregate fingerprint, not their values. Model-controlled shell children still
receive those variables blanked, while benchmark MCP children retain the
separate host-bridge environment policy.

Known path-valued credentials and certificate settings, including
`GOOGLE_APPLICATION_CREDENTIALS`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, and
`REQUESTS_CA_BUNDLE`, are validated and rebound read-only at stable per-variable
paths without mounting their parent directories.
Credential-directory inspection rejects nested symlinks and non-regular
entries and is bounded to 4,096 files, 64 MiB, and depth 16 before hashing or
mounting.
An auth file is read-only and copied into each isolated process through
`OPENCODE_AUTH_CONTENT`. Resume compatibility fingerprints the OpenCode and Bun
binaries/versions, bubblewrap path/version/content, TypeScript worker and Python
adapter/orchestration sources, exact effective system/configured initial prompt
content, relevant provider/auth inputs, and all exposed worker/startup sandbox
settings. A partial resume recomputes inherited effective prompt identity from
the current parent-pool child prompt and rejects a missing or mismatched hash.
Only pinned OpenCode `1.18.29` is source-audited (official tag `v1.18.29`,
commit `16747470f976aca3d362ad730bcd3fe82ecc2c9a`).

Host-side MCP commands receive only a small fixed base environment plus that
server's explicitly configured environment. OpenCode server credentials, auth
content, and provider keys are never forwarded to the host MCP process.

Private config roots contain a dependency declaration, matching root lock entry,
and an empty `node_modules` directory for the pinned OpenCode plugin version.
OpenCode's source then skips its detached dependency installer; npm is also
forced offline, so rollout startup cannot download config/plugin dependencies.

Assistant final prose is intentionally preserved in durable `WorkerResult`
output. Generic redaction protects protocol failures and sensitive MCP events,
but cannot soundly guarantee that a model will not repeat a benchmark answer in
ordinary prose. Benchmark answer privacy must therefore rely on tool-specific
redaction and benchmark policy, not semantic guessing over assistant text.

Bubblewrap materially limits filesystem and process access, but network access
is still allowed and the rollout workspace plus explicit archive/shared roots
remain writable. For evaluated benchmarks, session policy removes native
`bash`/`shell` tools and denies external-directory access. The fixed OpenCode
plugin also overwrites selected provider credentials, auth content, and server
tokens with empty values in any native shell child environment; this protects
trusted open-ended shell use from ordinary inheritance.

The unavoidable limitation is that provider credentials must still exist in the
OpenCode server process so it can call the provider. A defect in the audited
OpenCode process or fixed plugin could therefore access them, and allowed
network access remains an exfiltration surface. This is the strongest current
OpenCode-only fail-closed benchmark policy, not a hostile-use or Codex-parity
claim. Credential-hostile OpenCode rollouts remain unsupported.

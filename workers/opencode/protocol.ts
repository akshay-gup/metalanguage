import type {
  Event as OpenCodeEvent,
  McpStatus,
  Part,
  SessionCreateData,
  SessionCreateResponse,
  SessionMessagesResponse,
  SessionPromptAsyncData,
} from "../../third_party/opencode/packages/sdk/js/src/gen/types.gen.ts"

export type {
  McpStatus,
  OpenCodeEvent,
  Part,
  SessionCreateResponse,
  SessionMessagesResponse,
}

export type PermissionRule = {
  permission: string
  pattern: string
  action: "allow" | "deny" | "ask"
}

export type McpLocalConfig = {
  type: "local"
  command: string[]
  cwd?: string
  environment?: Record<string, string>
  enabled?: boolean
  timeout?: number
}

export type SessionCreateBody = NonNullable<SessionCreateData["body"]> & {
  permission?: PermissionRule[]
}

export type SessionPromptBody = NonNullable<SessionPromptAsyncData["body"]> & {
  variant?: string
}

export type McpServerInput = {
  command: string
  args?: string[]
  cwd?: string
  env?: Record<string, string>
  required?: boolean
  enabled_tools: string[]
  default_tools_approval_mode?: string
  startup_timeout_sec?: number
  tool_timeout_sec?: number
}

export type McpToolSelector = { server: string; tool: string }

export type CustomProviderInput = {
  provider_id: string
  provider_name: string
  npm: "@ai-sdk/openai-compatible" | "@ai-sdk/openai"
  api_mode: "chat_completions" | "responses"
  base_url: string
  api_key_env: string
  headers: Record<string, string>
  model_id: string
  limits: { context: number; output: number } | null
}

export type RunnerRequest = {
  opencode_bin: string
  allowed_versions?: string[]
  allowed_bun_versions?: string[]
  model: string
  cwd: string
  state_root: string
  initial_user_text?: string | null
  system_instructions?: string | null
  agent?: string | null
  variant?: string | null
  timeout_seconds?: number | null
  startup_timeout_seconds?: number | null
  auth_file?: string | null
  provider_env_names?: string[]
  custom_provider?: CustomProviderInput | null
  spawn_child_handler_command?: string[] | null
  mcp_servers?: Record<string, McpServerInput>
  sensitive_mcp_tools?: McpToolSelector[]
  sandbox?: {
    mode: "none" | "bubblewrap"
    network: "allow" | "none"
    bubblewrap_bin?: string | null
    read_only_roots?: string[]
    read_only_mounts?: Array<{ source: string; target: string }>
    writable_roots?: string[]
    masked_paths?: string[]
  }
  test_provider_config?: Record<string, unknown>
}

export type TranslatedMcpServer = {
  sourceName: string
  configName: string
  required: boolean
  startupTimeoutSeconds: number
  expectedToolIds: Set<string>
}

export type TranslatedMcp = {
  config: Record<string, McpLocalConfig>
  servers: TranslatedMcpServer[]
  permissionRules: PermissionRule[]
  sensitiveToolIds: Set<string>
}

export function parseModel(value: string): [string, string] {
  const separator = value.indexOf("/")
  if (separator <= 0 || separator === value.length - 1) {
    throw new Error("OpenCode model must use non-empty provider/model syntax")
  }
  return [value.slice(0, separator), value.slice(separator + 1)]
}

const CUSTOM_PROVIDER_MODES = {
  "@ai-sdk/openai-compatible": "chat_completions",
  "@ai-sdk/openai": "responses",
} as const

const MAX_CUSTOM_PROVIDER_LIMIT = 100_000_000

export function customProviderConfig(
  model: string,
  input: CustomProviderInput | null | undefined,
): Record<string, unknown> | undefined {
  if (!input) return undefined
  if (!isRecord(input)) throw new Error("custom provider configuration is invalid")
  if (
    typeof input.provider_id !== "string" ||
    typeof input.provider_name !== "string" ||
    typeof input.npm !== "string" ||
    typeof input.api_mode !== "string" ||
    typeof input.base_url !== "string" ||
    typeof input.api_key_env !== "string" ||
    typeof input.model_id !== "string" ||
    !isRecord(input.headers)
  ) {
    throw new Error("custom provider configuration is invalid")
  }
  const [providerID, modelID] = parseModel(model)
  if (providerID !== input.provider_id || modelID !== input.model_id) {
    throw new Error("custom provider identity does not match the requested model")
  }
  if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(input.provider_id)) {
    throw new Error("custom provider ID is invalid")
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$/.test(input.model_id)) {
    throw new Error("custom provider model ID is invalid")
  }
  const expectedMode = CUSTOM_PROVIDER_MODES[input.npm]
  if (!expectedMode || input.api_mode !== expectedMode) {
    throw new Error("custom provider package is not bundled for the requested API mode")
  }
  if (
    !input.provider_name ||
    input.provider_name !== input.provider_name.trim() ||
    input.provider_name.length > 128 ||
    [...input.provider_name].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  ) {
    throw new Error("custom provider name is invalid")
  }
  let endpoint: URL
  try {
    endpoint = new URL(input.base_url)
  } catch {
    throw new Error("custom provider base URL is invalid")
  }
  if (
    input.base_url.length > 2048 ||
    endpoint.username ||
    endpoint.password ||
    endpoint.search ||
    endpoint.hash
  ) {
    throw new Error("custom provider base URL is invalid")
  }
  const hostname = endpoint.hostname.toLowerCase().replace(/^\[|\]$/g, "")
  const loopback = hostname === "localhost" || hostname === "::1" || /^127(?:\.\d{1,3}){3}$/.test(hostname)
  if (!(["http:", "https:"] as string[]).includes(endpoint.protocol) || (endpoint.protocol === "http:" && !loopback)) {
    throw new Error("custom provider base URL requires HTTPS unless it is loopback")
  }
  const envName = /^[A-Za-z][A-Za-z0-9_]{0,127}$/
  const transportEnvironment = new Set(["LANG", "LC_ALL", "LC_CTYPE", "NO_COLOR", "REQUESTS_CA_BUNDLE", "SSL_CERT_DIR", "SSL_CERT_FILE", "TERM", "TZ", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AZURE_AUTH_LOCATION", "CURL_CA_BUNDLE", "GOOGLE_APPLICATION_CREDENTIALS"])
  const validEnvironmentName = (value: unknown): value is string =>
    typeof value === "string" &&
    envName.test(value) &&
    !transportEnvironment.has(value) &&
    !["HOME", "PATH", "TMPDIR"].includes(value) &&
    !value.startsWith("XDG_") &&
    !value.startsWith("OPENCODE_") &&
    !value.startsWith("METALANGUAGE_")
  if (!validEnvironmentName(input.api_key_env)) throw new Error("custom provider API key environment name is invalid")
  const headers: Record<string, string> = {}
  const unsafeHeaders = new Set([
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
  ])
  const seenHeaders = new Set<string>()
  for (const [name, environmentName] of Object.entries(input.headers)) {
    const normalized = name.toLowerCase()
    if (
      !/^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$/.test(name) ||
      !validEnvironmentName(environmentName) ||
      unsafeHeaders.has(normalized) ||
      seenHeaders.has(normalized)
    ) {
      throw new Error("custom provider header configuration is invalid")
    }
    seenHeaders.add(normalized)
    headers[name] = `{env:${environmentName}}`
  }
  if (
    input.limits !== null &&
    (!isRecord(input.limits) ||
      !Number.isSafeInteger(input.limits.context) ||
      input.limits.context <= 0 ||
      input.limits.context > MAX_CUSTOM_PROVIDER_LIMIT ||
      !Number.isSafeInteger(input.limits.output) ||
      input.limits.output <= 0 ||
      input.limits.output > MAX_CUSTOM_PROVIDER_LIMIT)
  ) {
    throw new Error("custom provider limits are invalid")
  }
  return {
    [input.provider_id]: {
      npm: input.npm,
      name: input.provider_name,
      options: {
        baseURL: input.base_url,
        apiKey: `{env:${input.api_key_env}}`,
        ...(Object.keys(headers).length ? { headers } : {}),
      },
      models: {
        [input.model_id]: {
          name: input.model_id,
          ...(input.limits ? { limit: input.limits } : {}),
        },
      },
    },
  }
}

export function sanitizeIdentifier(value: string): string {
  return value.replaceAll(/[^a-zA-Z0-9_-]/g, "_")
}

export function translateMcp(
  servers: Record<string, McpServerInput>,
  sensitive: McpToolSelector[],
  benchmarkPolicy = Object.keys(servers).length > 0,
): TranslatedMcp {
  const config: Record<string, McpLocalConfig> = {}
  const translated: TranslatedMcpServer[] = []
  const configNames = new Set<string>()
  const allToolIds = new Set<string>()
  const lookup = new Map<string, string>()
  const permissionRules: PermissionRule[] = [
    { permission: "*", pattern: "*", action: "allow" },
    { permission: "question", pattern: "*", action: "deny" },
    { permission: "task", pattern: "*", action: "deny" },
    ...(benchmarkPolicy
      ? [
          { permission: "bash", pattern: "*", action: "deny" } as const,
          { permission: "shell", pattern: "*", action: "deny" } as const,
          { permission: "external_directory", pattern: "*", action: "deny" } as const,
        ]
      : []),
  ]

  for (const [sourceName, server] of Object.entries(servers).sort(([a], [b]) => a.localeCompare(b))) {
    if (!sourceName.trim() || !server.command?.trim()) {
      throw new Error("MCP server names and commands must be non-empty")
    }
    if (!Array.isArray(server.enabled_tools) || server.enabled_tools.length === 0) {
      throw new Error(`MCP server ${sourceName} requires a non-empty enabled_tools allowlist`)
    }
    if (server.default_tools_approval_mode !== "approve") {
      throw new Error(`MCP server ${sourceName} must use default_tools_approval_mode=approve`)
    }
    const configName = `mcp__${sanitizeIdentifier(sourceName)}_`
    if (configNames.has(configName)) throw new Error("MCP server names collide after OpenCode sanitization")
    configNames.add(configName)

    const timeoutSeconds = Math.max(1, server.tool_timeout_sec ?? 30)
    config[configName] = {
      type: "local",
      command: [server.command, ...(server.args ?? [])],
      environment: server.env ?? {},
      ...(server.cwd ? { cwd: server.cwd } : {}),
      enabled: true,
      timeout: timeoutSeconds * 1000,
    }

    const expectedToolIds = new Set<string>()
    permissionRules.push({ permission: `${configName}_*`, pattern: "*", action: "deny" })
    for (const tool of server.enabled_tools) {
      if (typeof tool !== "string" || !tool.trim()) {
        throw new Error(`MCP server ${sourceName} has an empty enabled tool name`)
      }
      const toolId = `${configName}_${sanitizeIdentifier(tool)}`
      if (allToolIds.has(toolId)) throw new Error("MCP enabled tools collide after OpenCode sanitization")
      allToolIds.add(toolId)
      expectedToolIds.add(toolId)
      lookup.set(`${sourceName}\0${tool}`, toolId)
      permissionRules.push({ permission: toolId, pattern: "*", action: "allow" })
    }
    translated.push({
      sourceName,
      configName,
      required: server.required ?? false,
      startupTimeoutSeconds: Math.max(1, server.startup_timeout_sec ?? 10),
      expectedToolIds,
    })
  }

  const sensitiveToolIds = new Set<string>()
  for (const selector of sensitive) {
    const toolId = lookup.get(`${selector.server}\0${selector.tool}`)
    if (!toolId) {
      throw new Error(
        `sensitive_mcp_tools references an unconfigured or disabled MCP tool: ${selector.server}/${selector.tool}`,
      )
    }
    if (sensitiveToolIds.has(toolId)) {
      throw new Error("sensitive_mcp_tools contains a duplicate server/tool pair")
    }
    sensitiveToolIds.add(toolId)
  }

  return { config, servers: translated, permissionRules, sensitiveToolIds }
}

export class SseDecoder {
  private buffer = ""
  private data: string[] = []
  private readonly decoder = new TextDecoder("utf-8", { fatal: true })

  push(chunk: Uint8Array): unknown[] {
    this.buffer += this.decoder.decode(chunk, { stream: true })
    const output: unknown[] = []
    while (true) {
      const index = this.buffer.indexOf("\n")
      if (index < 0) break
      let line = this.buffer.slice(0, index)
      this.buffer = this.buffer.slice(index + 1)
      if (line.endsWith("\r")) line = line.slice(0, -1)
      if (!line) {
        if (this.data.length) {
          const payload = this.data.join("\n")
          this.data = []
          try {
            output.push(JSON.parse(payload))
          } catch (error) {
            throw new Error(`malformed OpenCode SSE JSON (${payload.length} characters)`, { cause: error })
          }
        }
      } else if (line.startsWith("data:")) {
        this.data.push(line.slice(5).trimStart())
      }
    }
    return output
  }
}

export type Terminal = "continue" | "idle" | "error"

type PermissionAskedEvent = {
  type: "permission.asked"
  properties: { sessionID?: string }
}

export class EventNormalizer {
  private readonly toolStatus = new Map<string, string>()
  private readonly messageRoles = new Map<string, string>()
  private readonly assistantOrder: string[] = []
  private readonly textOrderByMessage = new Map<string, string[]>()
  private readonly textParts = new Map<string, { messageID: string; text: string }>()
  private turnStarted = false
  error?: [string, string]

  constructor(
    private readonly sessionId: string,
    private readonly sensitiveToolIds: Set<string>,
  ) {}

  finalText(): string {
    const messageID = this.assistantOrder.at(-1)
    if (!messageID) return ""
    return (this.textOrderByMessage.get(messageID) ?? [])
      .map((id) => this.textParts.get(id)?.text)
      .filter((text): text is string => text !== undefined)
      .join("\n")
  }

  handle(event: unknown): { events: Record<string, unknown>[]; terminal: Terminal } {
    const output: Record<string, unknown>[] = []
    const record = isRecord(event) ? event : {}
    const eventType = typeof record.type === "string" ? record.type : ""
    const properties = isRecord(record.properties) ? record.properties : {}

    if (eventType === "session.status") {
      if (properties.sessionID !== this.sessionId) return { events: output, terminal: "continue" }
      const status = isRecord(properties.status) ? properties.status.type : undefined
      if (status === "busy" && !this.turnStarted) {
        this.turnStarted = true
        output.push({ event: "turn_started" })
      } else if (status === "retry") {
        output.push({ event: "warning", message: "OpenCode provider request is retrying" })
      } else if (status === "idle" && this.turnStarted) {
        return { events: output, terminal: "idle" }
      }
      return { events: output, terminal: "continue" }
    }

    if (eventType === "session.error") {
      if (properties.sessionID !== undefined && properties.sessionID !== this.sessionId) {
        return { events: output, terminal: "continue" }
      }
      const error = isRecord(properties.error) ? properties.error : {}
      const code = providerErrorCode(error.name)
      const message = safeErrorMessage(code)
      this.error = [code, message]
      output.push({ event: "error", error_code: code, error_message: message })
      return { events: output, terminal: "error" }
    }

    if (eventType === "permission.asked") {
      if (properties.sessionID === this.sessionId) {
        const message = "OpenCode requested interactive permission in a noninteractive rollout"
        this.error = ["permission_requested", message]
        output.push({ event: "error", error_code: "permission_requested", error_message: message })
        return { events: output, terminal: "error" }
      }
      return { events: output, terminal: "continue" }
    }

    if (eventType === "message.updated") {
      const info = isRecord(properties.info) ? properties.info : undefined
      if (!info || info.sessionID !== this.sessionId || typeof info.id !== "string") {
        return { events: output, terminal: "continue" }
      }
      const role = typeof info.role === "string" ? info.role : ""
      this.messageRoles.set(info.id, role)
      if (role === "assistant" && !this.assistantOrder.includes(info.id)) {
        this.assistantOrder.push(info.id)
      }
      return { events: output, terminal: "continue" }
    }

    if (eventType !== "message.part.updated") return { events: output, terminal: "continue" }
    const part = isRecord(properties.part) ? properties.part : undefined
    if (!part || part.sessionID !== this.sessionId) return { events: output, terminal: "continue" }
    const partId = typeof part.id === "string" ? part.id : ""

    if (part.type === "text" && typeof part.text === "string") {
      const messageID = typeof part.messageID === "string" ? part.messageID : ""
      if (!partId || !messageID) return { events: output, terminal: "continue" }
      if (!this.textParts.has(partId)) {
        const order = this.textOrderByMessage.get(messageID) ?? []
        order.push(partId)
        this.textOrderByMessage.set(messageID, order)
      }
      this.textParts.set(partId, { messageID, text: part.text })
      if (this.messageRoles.get(messageID) === "assistant" && isRecord(part.time) && part.time.end !== undefined) {
        output.push({ event: "agent_message", text: cappedString(part.text) })
      }
      return { events: output, terminal: "continue" }
    }

    if (part.type === "tool") {
      const tool = typeof part.tool === "string" ? part.tool : "unknown"
      const state = isRecord(part.state) ? part.state : {}
      const status = typeof state.status === "string" ? state.status : "unknown"
      if (this.toolStatus.get(partId) === status) return { events: output, terminal: "continue" }
      this.toolStatus.set(partId, status)
      const sensitive = this.sensitiveToolIds.has(tool)
      if (status === "pending" || status === "running") {
        output.push({
          event: "tool_begin",
          tool,
          call_id: partId,
          arguments: loggedPayload(state.input, sensitive),
        })
      } else if (status === "completed" || status === "error") {
        output.push({
          event: "tool_end",
          tool,
          call_id: partId,
          status,
          result: loggedPayload(state.output, sensitive),
          error: loggedPayload(state.error, sensitive),
        })
      }
      return { events: output, terminal: "continue" }
    }

    if (part.type === "file") {
      output.push({
        event: "attachment",
        mime: part.mime,
        filename: part.filename,
        payload: { redacted: true },
      })
    }
    return { events: output, terminal: "continue" }
  }
}

function providerErrorCode(value: unknown): string {
  if (
    value === "ProviderAuthError" ||
    value === "UnknownError" ||
    value === "MessageOutputLengthError" ||
    value === "MessageAbortedError" ||
    value === "APIError"
  ) {
    return value
  }
  return "opencode_session_error"
}

function loggedPayload(value: unknown, sensitive: boolean): unknown {
  return sensitive ? { redacted: true } : scrubValue(value)
}

export function scrubValue(value: unknown): unknown {
  if (typeof value === "string") {
    return value.startsWith("data:") || value.length > 4096 || looksSensitiveString(value)
      ? { redacted: true, characters: value.length }
      : value
  }
  if (Array.isArray(value)) return value.map(scrubValue)
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => {
        const lowered = key.toLowerCase()
        return [
          key,
          /(authorization|token|api.?key|password|secret|credential|cookie|session.?key|private.?key)/.test(lowered)
            ? { redacted: true }
            : scrubValue(item),
        ]
      }),
    )
  }
  return value ?? null
}

function looksSensitiveString(value: string): boolean {
  return /(?:^|[\s=:])(sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)/i.test(
    value,
  )
}

export function safeErrorMessage(code: string): string {
  return `OpenCode request failed (${safeErrorCode(code)})`
}

export function safeErrorCode(value: unknown, fallback = "unknown"): string {
  if (typeof value !== "string") return fallback
  const code = value.slice(0, 512).replaceAll(/[^a-zA-Z0-9_.-]/g, "_").slice(0, 128)
  return code || fallback
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

export function cappedString(value: string, max = 4096): string {
  return value.length <= max ? value : `${value.slice(0, max)}…`
}

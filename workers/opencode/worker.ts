#!/usr/bin/env bun

import { chmod, mkdir, readFile, realpath, writeFile } from "node:fs/promises"
import { join } from "node:path"

import {
  EventNormalizer,
  SseDecoder,
  cappedString,
  isRecord,
  parseModel,
  translateMcp,
  type McpStatus,
  type OpenCodeEvent,
  type RunnerRequest,
  type SessionCreateBody,
  type SessionCreateResponse,
  type SessionPromptBody,
  type SessionPromptResponse,
  type Terminal,
  type TranslatedMcp,
} from "./protocol.ts"
import { runSpawnBridgeFromStdio, SYSTEM_PLUGIN_SOURCE, TOOL_SOURCE } from "./spawn_bridge.ts"

class RunnerError extends Error {
  constructor(
    readonly code: string,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options)
  }
}

type WorkerEnvironment = Record<string, string>

function emit(event: Record<string, unknown>): void {
  process.stdout.write(`${JSON.stringify(event)}\n`)
}

function asRunnerError(code: string, error: unknown): RunnerError {
  return error instanceof RunnerError
    ? error
    : new RunnerError(code, error instanceof Error ? error.message : String(error), { cause: error })
}

function seconds(value: number | null | undefined, fallback: number): number {
  return Math.max(1, Number.isFinite(value) ? Number(value) : fallback)
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function withTimeout<T>(promise: Promise<T>, milliseconds: number, error: RunnerError): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = setTimeout(() => reject(error), milliseconds)
      }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

class AsyncQueue<T> {
  private values: T[] = []
  private waiters: Array<{ resolve: (value: T) => void; reject: (error: unknown) => void }> = []
  private closed?: unknown

  push(value: T): void {
    const waiter = this.waiters.shift()
    if (waiter) waiter.resolve(value)
    else this.values.push(value)
  }

  close(error: unknown): void {
    if (this.closed !== undefined) return
    this.closed = error
    for (const waiter of this.waiters.splice(0)) waiter.reject(error)
  }

  next(): Promise<T> {
    const value = this.values.shift()
    if (value !== undefined) return Promise.resolve(value)
    if (this.closed !== undefined) return Promise.reject(this.closed)
    return new Promise((resolve, reject) => this.waiters.push({ resolve, reject }))
  }
}

class ApiClient {
  constructor(
    private readonly baseUrl: URL,
    private readonly username: string,
    private readonly password: string,
    readonly directory: string,
  ) {}

  private url(path: string): URL {
    const url = new URL(path.replace(/^\//, ""), this.baseUrl)
    url.searchParams.set("directory", this.directory)
    return url
  }

  private headers(json = false): Headers {
    const headers = new Headers({ Authorization: `Basic ${btoa(`${this.username}:${this.password}`)}` })
    if (json) headers.set("Content-Type", "application/json")
    return headers
  }

  async request(path: string, init: RequestInit = {}): Promise<Response> {
    let response: Response
    try {
      response = await fetch(this.url(path), { ...init, headers: this.headers(init.body !== undefined) })
    } catch (error) {
      throw asRunnerError("opencode_http_error", error)
    }
    if (!response.ok) {
      const detail = cappedString(await response.text())
      throw new RunnerError(
        "opencode_http_error",
        `OpenCode API ${path} returned ${response.status}: ${detail}`,
      )
    }
    return response
  }

  async json<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await this.request(path, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const raw = await response.text()
    if (!raw) return null as T
    try {
      return JSON.parse(raw) as T
    } catch (error) {
      throw new RunnerError(
        "malformed_opencode_response",
        `OpenCode API ${path} returned malformed JSON`,
        { cause: error },
      )
    }
  }

  async abort(sessionId: string): Promise<void> {
    await this.json("POST", `/session/${sessionId}/abort`).catch(() => undefined)
  }

  async delete(sessionId: string): Promise<void> {
    await this.json("DELETE", `/session/${sessionId}`).catch(() => undefined)
  }
}

async function prepareStateRoot(path: string): Promise<string> {
  if (!path) throw new Error("state_root is empty")
  await mkdir(path, { recursive: true, mode: 0o700 })
  await chmod(path, 0o700)
  const root = await realpath(path)
  for (const relative of ["home", "config/tool", "config/plugin", "data", "state", "cache", "tmp"]) {
    const directory = join(root, relative)
    await mkdir(directory, { recursive: true, mode: 0o700 })
    await chmod(directory, 0o700)
  }
  const toolPath = join(root, "config/tool/spawn_child.js")
  const pluginPath = join(root, "config/plugin/metalanguage_system.js")
  await writeFile(toolPath, TOOL_SOURCE, { mode: 0o600 })
  await writeFile(pluginPath, SYSTEM_PLUGIN_SOURCE, { mode: 0o600 })
  await chmod(toolPath, 0o600)
  await chmod(pluginPath, 0o600)
  return root
}

function opencodeConfig(translated: TranslatedMcp): Record<string, unknown> {
  return {
    autoupdate: false,
    share: "disabled",
    permission: { "*": "allow", question: "deny", task: "deny" },
    mcp: translated.config,
  }
}

async function isolatedEnvironment(
  request: RunnerRequest,
  root: string,
  config: Record<string, unknown>,
  password: string,
): Promise<WorkerEnvironment> {
  const env: WorkerEnvironment = {}
  for (const [name, value] of Object.entries(process.env)) {
    if (value === undefined) continue
    if (name.startsWith("OPENCODE_") || name.startsWith("METALANGUAGE_OPENCODE_")) continue
    env[name] = value
  }
  Object.assign(env, {
    HOME: join(root, "home"),
    XDG_CONFIG_HOME: join(root, "config"),
    XDG_DATA_HOME: join(root, "data"),
    XDG_STATE_HOME: join(root, "state"),
    XDG_CACHE_HOME: join(root, "cache"),
    TMPDIR: join(root, "tmp"),
    OPENCODE_CONFIG_DIR: join(root, "config"),
    OPENCODE_DB: join(root, "data/opencode.db"),
    OPENCODE_CONFIG_CONTENT: JSON.stringify(config),
    OPENCODE_SERVER_USERNAME: "metalanguage",
    OPENCODE_SERVER_PASSWORD: password,
    OPENCODE_DISABLE_AUTOUPDATE: "1",
    OPENCODE_DISABLE_DEFAULT_PLUGINS: "1",
    OPENCODE_DISABLE_PROJECT_CONFIG: "1",
    OPENCODE_DISABLE_EXTERNAL_SKILLS: "1",
    OPENCODE_DISABLE_CLAUDE_CODE: "1",
    OPENCODE_DISABLE_LSP_DOWNLOAD: "1",
    OPENCODE_DISABLE_MODELS_FETCH: "1",
    OPENCODE_DISABLE_SHARE: "1",
    OPENCODE_PURE: "0",
    DO_NOT_TRACK: "1",
    METALANGUAGE_OPENCODE_BUN_BIN: process.execPath,
    METALANGUAGE_OPENCODE_WORKER_SCRIPT: import.meta.path,
  })
  if (request.spawn_child_handler_command) {
    env.METALANGUAGE_SPAWN_CHILD_HANDLER_COMMAND = JSON.stringify(request.spawn_child_handler_command)
  }
  if (request.system_instructions?.trim()) {
    env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS = request.system_instructions
  }
  if (request.auth_file) {
    const auth = await readFile(request.auth_file, "utf8")
    try {
      JSON.parse(auth)
    } catch (error) {
      throw new Error(`OpenCode auth file is not valid JSON: ${request.auth_file}`, { cause: error })
    }
    env.OPENCODE_AUTH_CONTENT = auth
  }
  return env
}

async function verifyVersion(request: RunnerRequest, env: WorkerEnvironment): Promise<void> {
  const process = Bun.spawn([request.opencode_bin, "--version"], {
    env,
    stdout: "pipe",
    stderr: "pipe",
  })
  let stdout: string
  let code: number
  try {
    const result = await withTimeout(
      Promise.all([new Response(process.stdout).text(), process.exited]),
      10_000,
      new RunnerError("opencode_version_timeout", "OpenCode --version timed out"),
    )
    stdout = result[0]
    code = result[1]
  } catch (error) {
    process.kill("SIGKILL")
    await process.exited
    throw error
  }
  if (code !== 0) throw new RunnerError("opencode_version_failed", `OpenCode --version exited ${code}`)
  const version = stdout.trim()
  if (request.allowed_versions?.length && !request.allowed_versions.includes(version)) {
    throw new RunnerError(
      "unsupported_opencode_version",
      `OpenCode version ${version} is not one of the source-audited versions: ${request.allowed_versions.join(", ")}`,
    )
  }
  emit({ event: "runtime_verified", runtime: "opencode", version })
}

type ServerProcess = ReturnType<typeof Bun.spawn>

function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal)
  } catch (error) {
    if (!isRecord(error) || error.code !== "ESRCH") throw error
  }
}

async function stopServer(server: ServerProcess): Promise<void> {
  const pid = server.pid
  try {
    signalGroup(pid, "SIGTERM")
  } catch {
    server.kill("SIGTERM")
  }
  await Promise.race([server.exited, sleep(3_000)])
  try {
    signalGroup(pid, "SIGKILL")
  } catch {
    server.kill("SIGKILL")
  }
  await Promise.race([server.exited, sleep(1_000)])
}

async function readServerUrl(server: ServerProcess, timeoutSeconds: number): Promise<URL> {
  const stream = server.stdout
  if (!(stream instanceof ReadableStream)) {
    throw new RunnerError("opencode_start_failed", "OpenCode stdout was unavailable")
  }
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  const found = (async () => {
    while (true) {
      const { value, done } = await reader.read()
      if (done) throw new RunnerError("opencode_start_failed", "OpenCode exited before reporting its server URL")
      buffer += decoder.decode(value, { stream: true })
      while (buffer.includes("\n")) {
        const index = buffer.indexOf("\n")
        const line = buffer.slice(0, index).replace(/\r$/, "")
        buffer = buffer.slice(index + 1)
        const prefix = "opencode server listening on "
        if (line.startsWith(prefix)) {
          void (async () => {
            while (!(await reader.read()).done) {}
          })()
          return new URL(`${line.slice(prefix.length).trim().replace(/\/$/, "")}/`)
        }
      }
    }
  })()
  return withTimeout(
    found,
    timeoutSeconds * 1000,
    new RunnerError("opencode_start_timeout", "OpenCode server startup timed out"),
  )
}

async function startServer(
  request: RunnerRequest,
  env: WorkerEnvironment,
): Promise<{ server: ServerProcess; baseUrl: URL }> {
  const server = Bun.spawn(
    [
      request.opencode_bin,
      "serve",
      "--hostname=127.0.0.1",
      "--port=0",
      "--log-level=ERROR",
    ],
    {
      cwd: request.cwd,
      env,
      stdout: "pipe",
      stderr: "ignore",
      detached: true,
    },
  )
  emit({ event: "runtime_process_started", runtime: "opencode", pid: server.pid })
  try {
    return {
      server,
      baseUrl: await readServerUrl(server, seconds(request.startup_timeout_seconds, 15)),
    }
  } catch (error) {
    await stopServer(server)
    throw error
  }
}

async function startSse(api: ApiClient, queue: AsyncQueue<unknown>): Promise<void> {
  const response = await api.request("/event")
  if (!response.body) throw new RunnerError("opencode_event_connect_failed", "OpenCode event body unavailable")
  void (async () => {
    const decoder = new SseDecoder()
    const reader = response.body!.getReader()
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) throw new RunnerError("opencode_event_closed", "OpenCode event stream closed")
        for (const event of decoder.push(value)) queue.push(event)
      }
    } catch (error) {
      queue.close(asRunnerError("malformed_opencode_event", error))
    }
  })()
}

async function validateMcp(api: ApiClient, translated: TranslatedMcp): Promise<void> {
  if (!translated.servers.length) return
  const started = Date.now()
  const connected = new Set<string>()
  while (true) {
    const status = await api.json<Record<string, McpStatus>>("GET", "/mcp")
    for (const server of translated.servers) {
      if (status[server.configName]?.status === "connected") connected.add(server.configName)
    }
    if (translated.servers.filter((server) => server.required).every((server) => connected.has(server.configName))) {
      break
    }
    const expired = translated.servers.find(
      (server) =>
        server.required &&
        !connected.has(server.configName) &&
        Date.now() - started >= server.startupTimeoutSeconds * 1000,
    )
    if (expired) {
      throw new RunnerError(
        "required_mcp_server_unavailable",
        `required MCP server ${expired.sourceName} did not connect`,
      )
    }
    await sleep(100)
  }
  emit({
    event: "mcp_ready",
    server_count: connected.size,
    enabled_tool_count: translated.servers.reduce((count, server) => count + server.expectedToolIds.size, 0),
    allowlist_enforcement: "session_permission_rules",
  })
}

function assistantText(response: SessionPromptResponse): string {
  return response.parts
    .filter((part) => part.type === "text")
    .map((part) => ("text" in part && typeof part.text === "string" ? part.text : ""))
    .filter(Boolean)
    .join("\n")
}

async function runSession(
  api: ApiClient,
  request: RunnerRequest,
  translated: TranslatedMcp,
  providerId: string,
  modelId: string,
  cancelled: Promise<void>,
): Promise<void> {
  const queue = new AsyncQueue<unknown>()
  await startSse(api, queue)
  const connected = await withTimeout(
    queue.next(),
    5_000,
    new RunnerError("opencode_event_timeout", "OpenCode event stream did not connect"),
  )
  if (!isRecord(connected) || connected.type !== "server.connected") {
    throw new RunnerError("opencode_event_protocol", "OpenCode event stream did not begin with server.connected")
  }

  await validateMcp(api, translated)
  const createBody: SessionCreateBody = {
    title: "Metalanguage rollout",
    permission: translated.permissionRules,
  }
  const session = await api.json<SessionCreateResponse>("POST", "/session", createBody)
  if (!session || typeof session.id !== "string") {
    throw new RunnerError("malformed_opencode_response", "session.create omitted id")
  }
  const sessionId = session.id
  emit({
    event: "thread_started",
    thread_id: sessionId,
    session_id: sessionId,
    model: request.model,
    model_provider: providerId,
    cwd: api.directory,
  })

  const body: SessionPromptBody = {
    model: { providerID: providerId, modelID: modelId },
    parts: [{ type: "text", text: request.initial_user_text ?? "Read README.md." }],
    ...(request.system_instructions?.trim() ? { system: request.system_instructions } : {}),
    ...(request.agent ? { agent: request.agent } : {}),
    ...(request.variant ? { variant: request.variant } : {}),
  }
  let promptResult: SessionPromptResponse | undefined
  let promptError: unknown
  const prompt = api
    .json<SessionPromptResponse>("POST", `/session/${sessionId}/message`, body)
    .then((value) => {
      promptResult = value
    })
    .catch((error) => {
      promptError = error
    })

  const timeoutSeconds = seconds(request.timeout_seconds, 3600)
  const deadline = sleep(timeoutSeconds * 1000).then(() => "timeout" as const)
  const cancellation = cancelled.then(() => "cancel" as const)
  const normalizer = new EventNormalizer(sessionId, translated.sensitiveToolIds)
  let terminal: Terminal = "continue"
  let eventPromise = queue.next()
  void eventPromise.catch(() => undefined)
  let promptPending = true

  while (terminal === "continue") {
    const outcome = await Promise.race([
      eventPromise.then((event) => ({ kind: "event" as const, event })),
      ...(promptPending ? [prompt.then(() => ({ kind: "prompt" as const }))] : []),
      deadline.then((kind) => ({ kind })),
      cancellation.then((kind) => ({ kind })),
    ])
    if (outcome.kind === "timeout") {
      await api.abort(sessionId)
      await api.delete(sessionId)
      throw new RunnerError("worker_timeout", `OpenCode rollout exceeded ${timeoutSeconds} seconds`)
    }
    if (outcome.kind === "cancel") {
      await api.abort(sessionId)
      await api.delete(sessionId)
      throw new RunnerError("worker_cancelled", "OpenCode rollout was cancelled")
    }
    if (outcome.kind === "prompt") {
      promptPending = false
      if (promptError) {
        await api.abort(sessionId)
        await api.delete(sessionId)
        throw asRunnerError("opencode_prompt_failed", promptError)
      }
      continue
    }
    eventPromise = queue.next()
    void eventPromise.catch(() => undefined)
    const reduced = normalizer.handle(outcome.event as OpenCodeEvent)
    for (const event of reduced.events) emit(event)
    terminal = reduced.terminal
  }

  if (terminal === "error") {
    await api.abort(sessionId)
  } else if (promptPending) {
    await withTimeout(
      prompt,
      5_000,
      new RunnerError("opencode_prompt_timeout", "OpenCode prompt response did not finish after idle"),
    )
  }
  await api.delete(sessionId)

  if (terminal === "error") {
    const [code, message] = normalizer.error ?? ["opencode_session_error", "OpenCode session failed"]
    throw new RunnerError(code, message)
  }
  if (promptError) throw asRunnerError("opencode_prompt_failed", promptError)
  const finalText = normalizer.finalText() || (promptResult ? assistantText(promptResult) : "")
  emit({ event: "turn_complete", final_text: finalText })
}

function randomSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

function parseRequest(value: unknown): RunnerRequest {
  if (!isRecord(value)) throw new Error("runner request must be a JSON object")
  for (const field of ["opencode_bin", "model", "cwd", "state_root"] as const) {
    if (typeof value[field] !== "string" || !value[field]) throw new Error(`runner request requires ${field}`)
  }
  return value as RunnerRequest
}

export async function runRequest(request: RunnerRequest, cancelled: Promise<void>): Promise<void> {
  let cwd: string
  try {
    cwd = await realpath(request.cwd)
  } catch (error) {
    throw new RunnerError("invalid_working_directory", String(error), { cause: error })
  }
  let root: string
  try {
    root = await prepareStateRoot(request.state_root)
  } catch (error) {
    throw asRunnerError("state_isolation_failed", error)
  }
  let providerId: string
  let modelId: string
  try {
    const parsed = parseModel(request.model)
    providerId = parsed[0]
    modelId = parsed[1]
  } catch (error) {
    throw asRunnerError("invalid_model", error)
  }
  let translated: TranslatedMcp
  try {
    translated = translateMcp(request.mcp_servers ?? {}, request.sensitive_mcp_tools ?? [])
  } catch (error) {
    throw asRunnerError("invalid_mcp_configuration", error)
  }
  let env: WorkerEnvironment
  try {
    env = await isolatedEnvironment(request, root, opencodeConfig(translated), randomSecret())
  } catch (error) {
    throw asRunnerError("state_isolation_failed", error)
  }
  await verifyVersion(request, env)
  const password = env.OPENCODE_SERVER_PASSWORD
  const { server, baseUrl } = await startServer({ ...request, cwd }, env)
  try {
    const api = new ApiClient(baseUrl, "metalanguage", password, cwd)
    await runSession(api, request, translated, providerId, modelId, cancelled)
  } finally {
    await stopServer(server)
  }
}

export async function main(): Promise<void> {
  if (process.argv[2] === "spawn-child-bridge") {
    await runSpawnBridgeFromStdio()
    return
  }
  let cancelResolve!: () => void
  const cancelled = new Promise<void>((resolve) => {
    cancelResolve = resolve
  })
  process.on("SIGTERM", cancelResolve)
  process.on("SIGINT", cancelResolve)
  try {
    const request = parseRequest(JSON.parse(await Bun.stdin.text()))
    await runRequest(request, cancelled)
    process.exit(0)
  } catch (error) {
    const normalized = asRunnerError("opencode_worker_failed", error)
    emit({
      event: "error",
      error_code: normalized.code,
      error_message: cappedString(normalized.message),
    })
    process.exit(1)
  }
}

if (import.meta.main) await main()

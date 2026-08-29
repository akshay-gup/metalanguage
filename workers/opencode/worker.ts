#!/usr/bin/env bun

import { chmod, mkdir, readFile, readdir, realpath, rm, writeFile } from "node:fs/promises"
import { basename, dirname, join, resolve } from "node:path"

import {
  EventNormalizer,
  SseDecoder,
  customProviderConfig,
  cappedString,
  isRecord,
  parseModel,
  safeErrorCode,
  safeErrorMessage,
  translateMcp,
  type McpStatus,
  type OpenCodeEvent,
  type RunnerRequest,
  type SessionCreateBody,
  type SessionCreateResponse,
  type SessionMessagesResponse,
  type SessionPromptBody,
  type Terminal,
  type TranslatedMcp,
} from "./protocol.ts"
import { runHandler, runSpawnBridgeFromStdio, SYSTEM_PLUGIN_SOURCE, TOOL_SOURCE } from "./spawn_bridge.ts"

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
    private readonly defaultTimeoutMs: number,
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

  async request(path: string, init: RequestInit = {}, timeoutMs = this.defaultTimeoutMs): Promise<Response> {
    let response: Response
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), Math.max(1, timeoutMs))
    const onAbort = () => controller.abort()
    init.signal?.addEventListener("abort", onAbort, { once: true })
    try {
      response = await fetch(this.url(path), {
        ...init,
        headers: this.headers(init.body !== undefined),
        signal: controller.signal,
      })
    } catch (error) {
      throw new RunnerError(
        controller.signal.aborted ? "opencode_http_timeout" : "opencode_http_error",
        controller.signal.aborted ? `OpenCode API ${path} timed out` : `OpenCode API ${path} failed`,
        { cause: error },
      )
    } finally {
      clearTimeout(timer)
      init.signal?.removeEventListener("abort", onAbort)
    }
    if (!response.ok) {
      await response.body?.cancel().catch(() => undefined)
      throw new RunnerError("opencode_http_error", `OpenCode API ${path} returned HTTP ${response.status}`)
    }
    return response
  }

  async json<T>(method: string, path: string, body?: unknown, timeoutMs?: number): Promise<T> {
    const response = await this.request(path, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }, timeoutMs)
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

  async noContent(method: string, path: string, body: unknown, timeoutMs: number): Promise<void> {
    const response = await this.request(
      path,
      { method, body: JSON.stringify(body) },
      timeoutMs,
    )
    if (response.status !== 204) {
      await response.body?.cancel().catch(() => undefined)
      throw new RunnerError(
        "malformed_opencode_response",
        `OpenCode API ${path} returned HTTP ${response.status}; expected 204`,
      )
    }
  }

  async abort(sessionId: string): Promise<void> {
    await this.json("POST", `/session/${sessionId}/abort`, undefined, 3_000).catch(() => undefined)
  }

  async delete(sessionId: string): Promise<void> {
    await this.json("DELETE", `/session/${sessionId}`, undefined, 3_000).catch(() => undefined)
  }
}

async function prepareStateRoot(path: string): Promise<string> {
  if (!path) throw new Error("state_root is empty")
  await mkdir(path, { recursive: true, mode: 0o700 })
  await chmod(path, 0o700)
  const root = await realpath(path)
  for (const relative of [
    "home",
    "config/opencode",
    "config/tool",
    "config/plugin",
    "data",
    "state",
    "cache",
    "tmp",
  ]) {
    const directory = join(root, relative)
    await mkdir(directory, { recursive: true, mode: 0o700 })
    await chmod(directory, 0o700)
  }
  const toolDirectory = join(root, "config/tool")
  for (const entry of await readdir(toolDirectory)) {
    if (entry.endsWith(".js")) await rm(join(toolDirectory, entry), { force: true })
  }
  const toolPath = join(root, "config/tool/spawn_child.js")
  const pluginPath = join(root, "config/plugin/metalanguage_system.js")
  const maskedFilePath = join(root, "masked-empty")
  await writeFile(toolPath, TOOL_SOURCE, { mode: 0o600 })
  await writeFile(pluginPath, SYSTEM_PLUGIN_SOURCE, { mode: 0o600 })
  await writeFile(maskedFilePath, "", { mode: 0o600 })
  await chmod(toolPath, 0o600)
  await chmod(pluginPath, 0o600)
  await chmod(maskedFilePath, 0o600)
  for (const configRoot of [join(root, "config"), join(root, "config/opencode")]) {
    const packagePath = join(configRoot, "package.json")
    const packageLockPath = join(configRoot, "package-lock.json")
    const gitignorePath = join(configRoot, ".gitignore")
    await mkdir(join(configRoot, "node_modules"), { recursive: true, mode: 0o700 })
    await writeFile(
      packagePath,
      `${JSON.stringify({ private: true, dependencies: { "@opencode-ai/plugin": "1.18.21" } }, null, 2)}\n`,
      { mode: 0o600 },
    )
    await writeFile(
      packageLockPath,
      `${JSON.stringify({
        name: "metalanguage-opencode-config",
        lockfileVersion: 3,
        requires: true,
        packages: { "": { dependencies: { "@opencode-ai/plugin": "1.18.21" } } },
      }, null, 2)}\n`,
      { mode: 0o600 },
    )
    await writeFile(gitignorePath, "node_modules\npackage.json\npackage-lock.json\n.gitignore\n", { mode: 0o600 })
    await chmod(packagePath, 0o600)
    await chmod(packageLockPath, 0o600)
    await chmod(gitignorePath, 0o600)
  }
  return root
}

type HostMcpBridge = {
  process: ReturnType<typeof Bun.spawn>
  socketPath: string
  childPid: number
}

function safeHostEnvironment(extra: Record<string, string>): Record<string, string> {
  const env: Record<string, string> = {
    PATH: process.env.PATH ?? "/usr/local/bin:/usr/bin:/bin",
    LANG: process.env.LANG ?? "C.UTF-8",
  }
  for (const name of ["LC_ALL", "LC_CTYPE", "NO_COLOR", "TZ"]) {
    const value = process.env[name]
    if (value !== undefined) env[name] = value
  }
  return { ...env, ...extra }
}

async function bridgeReady(
  bridge: ReturnType<typeof Bun.spawn>,
  timeoutSeconds: number,
): Promise<number> {
  if (!(bridge.stdout instanceof ReadableStream)) {
    throw new RunnerError("benchmark_mcp_bridge_failed", "benchmark MCP bridge stdout was unavailable")
  }
  const reader = bridge.stdout.getReader()
  const ready = (async () => {
    const decoder = new TextDecoder()
    let raw = ""
    while (true) {
      const { value, done } = await reader.read()
      if (done) throw new RunnerError("benchmark_mcp_bridge_failed", "benchmark MCP bridge exited during startup")
      raw += decoder.decode(value, { stream: true })
      const newline = raw.indexOf("\n")
      if (newline < 0) {
        if (raw.length > 4096) throw new RunnerError("benchmark_mcp_bridge_failed", "benchmark MCP bridge emitted invalid startup data")
        continue
      }
      let event: unknown
      try {
        event = JSON.parse(raw.slice(0, newline))
      } catch {
        throw new RunnerError("benchmark_mcp_bridge_failed", "benchmark MCP bridge emitted invalid startup data")
      }
      if (!isRecord(event) || event.event !== "ready" || !Number.isInteger(event.child_pid)) {
        throw new RunnerError("benchmark_mcp_bridge_failed", "benchmark MCP bridge omitted child identity")
      }
      void (async () => {
        while (!(await reader.read()).done) {}
      })()
      return Number(event.child_pid)
    }
  })()
  return withTimeout(
    ready,
    Math.max(1, timeoutSeconds) * 1000,
    new RunnerError("benchmark_mcp_bridge_timeout", "benchmark MCP bridge startup timed out"),
  )
}

async function startHostMcpBridges(
  request: RunnerRequest,
  translated: TranslatedMcp,
  root: string,
): Promise<{ bridges: HostMcpBridge[]; hostRoot?: string }> {
  if (!translated.servers.length) return { bridges: [] }
  if (request.sandbox?.mode !== "bubblewrap") {
    throw new RunnerError("benchmark_mcp_bridge_requires_sandbox", "benchmark MCP host bridge requires bubblewrap")
  }
  const hostRoot = join(dirname(root), `.opencode-mcp-host-${basename(root)}-${randomSecret().slice(0, 16)}`)
  await mkdir(hostRoot, { recursive: false, mode: 0o700 })
  await chmod(hostRoot, 0o700)
  const proxyPath = join(hostRoot, "mcp_socket_proxy.ts")
  await writeFile(proxyPath, await readFile(join(import.meta.dir, "mcp_socket_proxy.ts")), { mode: 0o500 })
  await chmod(proxyPath, 0o500)
  const bridges: HostMcpBridge[] = []
  try {
    for (const server of translated.servers) {
      const config = translated.config[server.configName]
      if (!config || config.type !== "local") throw new RunnerError("invalid_mcp_configuration", "benchmark MCP config is not local")
      const socketPath = join(hostRoot, `${server.configName}.sock`)
      const bridgeRequest = {
        socket_path: socketPath,
        command: [...config.command],
        ...(config.cwd ? { cwd: config.cwd } : {}),
        env: safeHostEnvironment(config.environment ?? {}),
        supervisor_pid: process.pid,
      }
      const bridge = Bun.spawn(
        [process.execPath, join(import.meta.dir, "mcp_host_bridge.ts"), JSON.stringify(bridgeRequest)],
        {
          env: safeHostEnvironment({}),
          stdin: "ignore",
          stdout: "pipe",
          stderr: "ignore",
          detached: true,
        },
      )
      emit({ event: "mcp_process_started", pid: bridge.pid })
      let childPid: number
      try {
        childPid = await bridgeReady(bridge, server.startupTimeoutSeconds)
      } catch (error) {
        await stopServer(bridge)
        throw error
      }
      emit({ event: "mcp_process_started", pid: childPid })
      bridges.push({ process: bridge, socketPath, childPid })
      config.command = [process.execPath, proxyPath, socketPath]
      config.cwd = request.cwd
      config.environment = Object.fromEntries(
        [
          ...(request.provider_env_names ?? []),
          "OPENCODE_AUTH_CONTENT",
          "OPENCODE_SERVER_PASSWORD",
          "METALANGUAGE_SPAWN_CHILD_TOKEN",
        ].map((name) => [name, ""]),
      )
    }
    return { bridges, hostRoot }
  } catch (error) {
    for (const bridge of bridges) await stopServer(bridge.process)
    await rm(hostRoot, { recursive: true, force: true })
    throw error
  }
}

async function stopHostMcpBridges(bridges: HostMcpBridge[], hostRoot?: string): Promise<void> {
  for (const bridge of bridges) await stopServer(bridge.process)
  if (hostRoot) await rm(hostRoot, { recursive: true, force: true })
}

function opencodeConfig(request: RunnerRequest, translated: TranslatedMcp): Record<string, unknown> {
  const config: Record<string, unknown> = {
    autoupdate: false,
    share: "disabled",
    permission: { "*": "allow", question: "deny", task: "deny" },
    mcp: translated.config,
  }
  let customProvider: Record<string, unknown> | undefined
  try {
    customProvider = customProviderConfig(request.model, request.custom_provider)
  } catch (error) {
    throw new RunnerError("invalid_custom_provider", "custom OpenCode provider configuration is invalid", {
      cause: error,
    })
  }
  if (customProvider) config.provider = customProvider
  if (request.test_provider_config !== undefined) {
    if (customProvider) {
      throw new RunnerError("invalid_custom_provider", "custom and test provider configuration cannot be combined")
    }
    if (process.env.METALANGUAGE_OPENCODE_OFFLINE_TEST !== "1") {
      throw new RunnerError("test_provider_forbidden", "test provider configuration requires offline test mode")
    }
    config.provider = request.test_provider_config
  }
  return config
}

async function isolatedEnvironment(
  request: RunnerRequest,
  root: string,
  config: Record<string, unknown>,
  password: string,
  callback?: { endpoint: string; token: string },
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
    npm_config_offline: "true",
    npm_config_audit: "false",
    npm_config_fund: "false",
    npm_config_update_notifier: "false",
  })
  if (callback) {
    env.METALANGUAGE_SPAWN_CHILD_ENDPOINT = callback.endpoint
    env.METALANGUAGE_SPAWN_CHILD_TOKEN = callback.token
  }
  env.METALANGUAGE_OPENCODE_PROVIDER_ENV_NAMES = JSON.stringify(request.provider_env_names ?? [])
  if (request.sandbox?.masked_paths?.[0]) {
    env.METALANGUAGE_OPENCODE_MASKED_PATH = request.sandbox.masked_paths[0]
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

function verifyBunVersion(request: RunnerRequest): void {
  const version = Bun.version
  if (request.allowed_bun_versions?.length && !request.allowed_bun_versions.includes(version)) {
    throw new RunnerError(
      "unsupported_bun_version",
      `Bun version ${version} is not source-audited`,
    )
  }
  emit({ event: "runtime_verified", runtime: "bun", version })
}

type ServerProcess = ReturnType<typeof Bun.spawn>

function addParentDirectories(command: string[], path: string): void {
  const missing: string[] = []
  let current = dirname(path)
  while (current !== "/" && !current.startsWith("/usr") && !current.startsWith("/etc")) {
    missing.push(current)
    current = dirname(current)
  }
  for (const directory of missing.reverse()) command.push("--dir", directory)
}

export async function sandboxedServerCommand(request: RunnerRequest, root: string): Promise<string[]> {
  const base = [request.opencode_bin, "serve", "--hostname=127.0.0.1", "--port=0", "--log-level=ERROR"]
  const sandbox = request.sandbox ?? { mode: "none" as const, network: "allow" as const }
  if (sandbox.mode === "none") return base
  if (sandbox.network !== "allow") {
    throw new RunnerError(
      "unsupported_sandbox_network_mode",
      "the HTTP worker boundary cannot reach a separately isolated network namespace",
    )
  }
  const bwrap = sandbox.bubblewrap_bin ?? "/usr/bin/bwrap"
  const command = [
    bwrap,
    "--die-with-parent",
    "--new-session",
    "--unshare-pid",
    "--unshare-ipc",
    "--unshare-uts",
    "--unshare-cgroup-try",
    "--ro-bind",
    "/usr",
    "/usr",
    "--ro-bind",
    "/etc",
    "/etc",
    "--symlink",
    "usr/bin",
    "/bin",
    "--symlink",
    "usr/lib",
    "/lib",
    "--symlink",
    "usr/lib64",
    "/lib64",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "--tmpfs",
    "/tmp",
  ]
  const readOnly = new Set([
    dirname(request.opencode_bin),
    dirname(process.execPath),
    ...(sandbox.read_only_roots ?? []),
  ])
  const writable = new Set([root, request.cwd, ...(sandbox.writable_roots ?? [])])
  const mounts = new Map<string, "read" | "write">()
  for (const path of writable) {
    const real = await realpath(path)
    mounts.set(real, "write")
  }
  for (const path of readOnly) {
    const real = await realpath(path)
    mounts.set(real, "read")
  }
  const orderedMounts = [...mounts.entries()].sort(([left], [right]) => {
    const depth = left.split("/").filter(Boolean).length - right.split("/").filter(Boolean).length
    return depth || left.localeCompare(right)
  })
  for (const [real, access] of orderedMounts) {
    addParentDirectories(command, real)
    command.push(access === "read" ? "--ro-bind" : "--bind", real, real)
  }
  for (const mount of sandbox.read_only_mounts ?? []) {
    const source = await realpath(mount.source)
    if (
      !mount.target.startsWith("/run/metalanguage/credentials/") &&
      resolve(mount.target) !== source
    ) {
      throw new RunnerError("invalid_sandbox_mount", "read-only mount target is not stable")
    }
    addParentDirectories(command, mount.target)
    command.push("--ro-bind", source, mount.target)
  }
  for (const path of sandbox.masked_paths ?? []) {
    const real = await realpath(path)
    command.push("--ro-bind", join(root, "masked-empty"), real)
  }
  command.push("--chdir", request.cwd, "--", ...base)
  return command
}

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
  root: string,
): Promise<{ server: ServerProcess; baseUrl: URL }> {
  const command = await sandboxedServerCommand(request, root)
  const server = Bun.spawn(
    command,
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

async function startSse(api: ApiClient, queue: AsyncQueue<unknown>, timeoutMs: number): Promise<void> {
  const response = await api.request("/event", {}, timeoutMs)
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
    const status = await api.json<Record<string, McpStatus>>("GET", "/mcp", undefined, 2_000)
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

async function verifyProcfs(): Promise<void> {
  await readFile("/proc/self/status", "utf8")
  const entries = await readdir("/proc")
  if (!entries.some((entry) => /^\d+$/.test(entry))) {
    throw new RunnerError("benchmark_mcp_bridge_failed", "benchmark MCP isolation requires procfs")
  }
}

export function finalAssistantText(messages: SessionMessagesResponse, userMessageId: string): string | undefined {
  const submittedUser = messages.some(
    (message) => message.info?.role === "user" && message.info.id === userMessageId,
  )
  if (!submittedUser) return undefined
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]!
    if (
      !message.info ||
      message.info.role !== "assistant" ||
      typeof message.info.id !== "string" ||
      message.info.parentID !== userMessageId ||
      message.info.error !== undefined ||
      typeof message.info.finish !== "string" ||
      message.info.finish === "tool-calls" ||
      message.info.finish === "unknown"
    ) continue
    const messageID = message.info.id
    if (!Array.isArray(message.parts)) return undefined
    const text = message.parts
      .filter((part) => part.type === "text" && part.messageID === messageID)
      .map((part) => ("text" in part && typeof part.text === "string" ? part.text : ""))
      .filter(Boolean)
      .join("\n")
    return text
  }
  return undefined
}

function messageId(): string {
  const encodedTime = (BigInt(Date.now()) * 0x1000n).toString(16).padStart(12, "0").slice(-12)
  return `msg_${encodedTime}${randomSecret().slice(0, 14)}`
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
  const startupTimeoutMs = seconds(request.startup_timeout_seconds, 15) * 1000
  await startSse(api, queue, startupTimeoutMs)
  const connected = await withTimeout(
    queue.next(),
    startupTimeoutMs,
    new RunnerError("opencode_event_timeout", "OpenCode event stream did not connect"),
  )
  if (!isRecord(connected) || connected.type !== "server.connected") {
    throw new RunnerError("opencode_event_protocol", "OpenCode event stream did not begin with server.connected")
  }

  await validateMcp(api, translated)
  if (translated.servers.length) await verifyProcfs()
  const createBody: SessionCreateBody = {
    title: "Metalanguage rollout",
    permission: translated.permissionRules,
  }
  const session = await api.json<SessionCreateResponse>(
    "POST",
    "/session",
    createBody,
    seconds(request.startup_timeout_seconds, 15) * 1000,
  )
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
    messageID: messageId(),
    model: { providerID: providerId, modelID: modelId },
    parts: [{ type: "text", text: request.initial_user_text ?? "Read README.md." }],
    ...(request.system_instructions?.trim() ? { system: request.system_instructions } : {}),
    ...(request.agent ? { agent: request.agent } : {}),
    ...(request.variant ? { variant: request.variant } : {}),
  }
  const timeoutSeconds = seconds(request.timeout_seconds, 3600)
  const deadline = sleep(timeoutSeconds * 1000).then(() => "timeout" as const)
  const cancellation = cancelled.then(() => "cancel" as const)
  const normalizer = new EventNormalizer(sessionId, translated.sensitiveToolIds)
  let terminal: Terminal = "continue"
  let completed = false
  try {
    try {
      await api.noContent(
        "POST",
        `/session/${sessionId}/prompt_async`,
        body,
        Math.min(startupTimeoutMs, 10_000),
      )
    } catch (error) {
      const code = error instanceof RunnerError && error.code === "opencode_http_timeout"
        ? "opencode_prompt_submit_timeout"
        : "opencode_prompt_submit_failed"
      throw new RunnerError(code, `OpenCode async prompt submission failed (${code})`, { cause: error })
    }

    while (terminal === "continue") {
      const outcome = await Promise.race([
        queue.next().then((event) => ({ kind: "event" as const, event })),
        deadline.then((kind) => ({ kind })),
        cancellation.then((kind) => ({ kind })),
      ])
      if (outcome.kind === "timeout") {
        throw new RunnerError("worker_timeout", `OpenCode rollout exceeded ${timeoutSeconds} seconds`)
      }
      if (outcome.kind === "cancel") {
        throw new RunnerError("worker_cancelled", "OpenCode rollout was cancelled")
      }
      const reduced = normalizer.handle(outcome.event as OpenCodeEvent)
      for (const event of reduced.events) emit(event)
      terminal = reduced.terminal
    }

    if (terminal === "error") {
      const [code, message] = normalizer.error ?? ["opencode_session_error", "OpenCode session failed"]
      throw new RunnerError(code, message)
    }
    const messages = await api.json<SessionMessagesResponse>(
      "GET",
      `/session/${sessionId}/message`,
      undefined,
      3_000,
    )
    if (!Array.isArray(messages)) {
      throw new RunnerError("malformed_opencode_response", "session.messages did not return a list")
    }
    const finalText = finalAssistantText(messages, body.messageID!)
    if (finalText === undefined) {
      throw new RunnerError(
        "malformed_opencode_response",
        "session.messages omitted the completed assistant response for the submitted turn",
      )
    }
    completed = true
    emit({ event: "turn_complete", final_text: finalText })
  } finally {
    if (!completed) await api.abort(sessionId)
    await api.delete(sessionId)
  }
}

function randomSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

function secretFingerprint(value: string): string {
  return new Bun.CryptoHasher("sha256").update(value).digest("hex")
}

export async function startSpawnCallback(command: string[], handlerTimeoutMs = 15_000): Promise<{
  endpoint: string
  token: string
  stop: () => void
}> {
  const token = randomSecret()
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      if (request.method !== "POST" || new URL(request.url).pathname !== "/spawn-child") {
        return new Response("not found", { status: 404 })
      }
      if (request.headers.get("authorization") !== `Bearer ${token}`) {
        return new Response("unauthorized", { status: 401 })
      }
      const length = Number(request.headers.get("content-length") ?? "0")
      if (!Number.isFinite(length) || length > 64 * 1024) {
        return new Response("request too large", { status: 413 })
      }
      try {
        const raw = await request.text()
        if (raw.length > 64 * 1024) return new Response("request too large", { status: 413 })
        const result = await runHandler(command, JSON.parse(raw), handlerTimeoutMs)
        return Response.json(result)
      } catch {
        return Response.json(
          {
            success: false,
            child_spawned: false,
            parent_continues: true,
            retryable: true,
            error_code: "spawn_child_bridge_invalid_request",
            error: "spawn_child bridge request was invalid",
          },
        )
      }
    },
  })
  return {
    endpoint: `http://127.0.0.1:${server.port}/spawn-child`,
    token,
    stop: () => server.stop(true),
  }
}

function parseRequest(value: unknown): RunnerRequest {
  if (!isRecord(value)) throw new Error("runner request must be a JSON object")
  for (const field of ["opencode_bin", "model", "cwd", "state_root"] as const) {
    if (typeof value[field] !== "string" || !value[field]) throw new Error(`runner request requires ${field}`)
  }
  return value as RunnerRequest
}

export async function runRequest(request: RunnerRequest, cancelled: Promise<void>): Promise<void> {
  verifyBunVersion(request)
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
  const hostMcp = await startHostMcpBridges(request, translated, root)
  if (hostMcp.hostRoot) {
    request.sandbox = {
      ...(request.sandbox ?? { mode: "bubblewrap", network: "allow" }),
      read_only_roots: [...(request.sandbox?.read_only_roots ?? []), hostMcp.hostRoot],
    }
  }
  let env: WorkerEnvironment
  let callback: Awaited<ReturnType<typeof startSpawnCallback>> | undefined
  try {
    callback = request.spawn_child_handler_command?.length
      ? await startSpawnCallback(request.spawn_child_handler_command)
      : undefined
    env = await isolatedEnvironment(
      request,
      root,
      opencodeConfig(request, translated),
      randomSecret(),
      callback,
    )
  } catch (error) {
    callback?.stop()
    await stopHostMcpBridges(hostMcp.bridges, hostMcp.hostRoot)
    throw asRunnerError("state_isolation_failed", error)
  }
  try {
    await verifyVersion(request, env)
    const password = env.OPENCODE_SERVER_PASSWORD
    const { server, baseUrl } = await startServer({ ...request, cwd }, env, root)
    try {
      emit({
        event: "isolation_verified",
        server_port: Number(baseUrl.port),
        auth_sha256: secretFingerprint(password),
      })
      const api = new ApiClient(
        baseUrl,
        "metalanguage",
        password,
        cwd,
        seconds(request.startup_timeout_seconds, 15) * 1000,
      )
      await runSession(api, request, translated, providerId, modelId, cancelled)
    } finally {
      await stopServer(server)
    }
  } finally {
    callback?.stop()
    await stopHostMcpBridges(hostMcp.bridges, hostMcp.hostRoot)
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
      error_code: safeErrorCode(normalized.code),
      error_message: safeErrorMessage(normalized.code),
    })
    process.exit(1)
  }
}

if (import.meta.main) await main()

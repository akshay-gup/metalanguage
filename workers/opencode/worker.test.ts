import { describe, expect, test } from "bun:test"
import { lstat, mkdir, mkdtemp, readlink, realpath, rm, symlink, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { dirname, join, resolve } from "node:path"

import {
  EventNormalizer,
  SseDecoder,
  customProviderConfig,
  safeErrorCode,
  translateMcp,
  type McpServerInput,
  type RunnerRequest,
} from "./protocol.ts"
import {
  finalAssistantText,
  initialSystemInstructions,
  opencodeConfig,
  sandboxedServerCommand,
  startDirectoryAgentsCallback,
  startSpawnCallback,
} from "./worker.ts"
import {
  runDirectoryAgentsHandler,
  runHandler,
  SYSTEM_PLUGIN_SOURCE,
  systemPluginSource,
  TOOL_SOURCE,
} from "./spawn_bridge.ts"

function mcpServer(): McpServerInput {
  return {
    command: "/usr/bin/python3",
    args: ["-m", "utils.supergpqa_mcp"],
    cwd: "/workspace",
    env: { CONTEXT: "/private/context.json" },
    required: true,
    enabled_tools: ["submit_solution"],
    default_tools_approval_mode: "approve",
    startup_timeout_sec: 7,
    tool_timeout_sec: 31,
  }
}

describe("OpenCode native protocol adapter", () => {
  test("mounts only the resolved resolver file after its empty parent directories", async () => {
    const root = await mkdtemp(join(tmpdir(), "metalanguage-opencode-resolver-"))
    try {
      const cwd = join(root, "work")
      const state = join(root, "state")
      const resolver = join(root, "etc", "resolv.conf")
      const target = join(root, "run", "systemd", "resolve", "stub-resolv.conf")
      const source = join(root, "source", "actual-resolv.conf")
      await mkdir(cwd, { recursive: true })
      await mkdir(state, { recursive: true })
      await mkdir(join(root, "etc"), { recursive: true })
      await mkdir(dirname(target), { recursive: true })
      await mkdir(dirname(source), { recursive: true })
      await writeFile(source, "nameserver 127.0.0.53\n")
      await symlink(source, target)
      await symlink("../run/systemd/resolve/stub-resolv.conf", resolver)
      const request: RunnerRequest = {
        opencode_bin: "/usr/bin/true",
        model: "fixture/model",
        cwd,
        state_root: state,
        sandbox: {
          mode: "bubblewrap",
          network: "allow",
          bubblewrap_bin: "/usr/bin/bwrap",
          writable_roots: [join(root, "run")],
        },
      }
      const command = await sandboxedServerCommand(request, state, resolver)
      const mountIndex = command.findIndex(
        (value, index) => value === "--ro-bind" && command[index + 1] === source && command[index + 2] === target,
      )
      expect(mountIndex).toBeGreaterThan(-1)
      expect(
        command.findIndex(
          (value, index) => value === "--ro-bind" && command[index + 1] === "/etc",
        ),
      ).toBeLessThan(mountIndex)
      expect(
        command.findIndex(
          (value, index) => value === "--bind" && command[index + 1] === join(root, "run"),
        ),
      ).toBeLessThan(mountIndex)
      for (const parent of [root, join(root, "run"), join(root, "run", "systemd"), dirname(target)]) {
        expect(
          command.findIndex((value, index) => value === "--dir" && command[index + 1] === parent),
        ).toBeLessThan(mountIndex)
      }
      expect(
        command.findIndex(
          (value, index) => value === "--ro-bind" && command[index + 1] === dirname(target),
        ),
      ).toBe(-1)
      expect(
        command.findIndex(
          (value, index) => value === "--bind" && command[index + 1] === target,
        ),
      ).toBe(-1)
      expect(command.indexOf("--chdir")).toBeGreaterThan(mountIndex)
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  test("uses the /etc mount for a regular resolver and fails closed on invalid resolver paths", async () => {
    const root = await mkdtemp(join(tmpdir(), "metalanguage-opencode-resolver-invalid-"))
    try {
      const cwd = join(root, "work")
      const state = join(root, "state")
      const request: RunnerRequest = {
        opencode_bin: "/usr/bin/true",
        model: "fixture/model",
        cwd,
        state_root: state,
        sandbox: { mode: "bubblewrap", network: "allow", bubblewrap_bin: "/usr/bin/bwrap" },
      }
      await mkdir(cwd, { recursive: true })
      await mkdir(state, { recursive: true })
      const regular = join(root, "regular-resolv.conf")
      await writeFile(regular, "nameserver 192.0.2.1\n")
      const command = await sandboxedServerCommand(request, state, regular)
      expect(
        command.findIndex(
          (value, index) => value === "--ro-bind" && command[index + 1] === regular && command[index + 2] === regular,
        ),
      ).toBe(-1)

      const broken = join(root, "broken-resolv.conf")
      await symlink("missing", broken)
      await expect(sandboxedServerCommand(request, state, broken)).rejects.toThrow(
        "OpenCode resolver configuration must resolve to a readable regular file",
      )
      const directory = join(root, "resolver-directory")
      await mkdir(directory)
      await expect(sandboxedServerCommand(request, state, directory)).rejects.toThrow(
        "OpenCode resolver configuration must resolve to a readable regular file",
      )
      const directoryLink = join(root, "resolver-directory-link")
      await symlink(directory, directoryLink)
      await expect(sandboxedServerCommand(request, state, directoryLink)).rejects.toThrow(
        "OpenCode resolver configuration must resolve to a readable regular file",
      )
      await expect(sandboxedServerCommand(request, state, "relative-resolv.conf")).rejects.toThrow(
        "OpenCode resolver configuration must resolve to a readable regular file",
      )
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  test("does not expose a broad /run mount for the host resolver", async () => {
    const root = await mkdtemp(join(tmpdir(), "metalanguage-opencode-host-resolver-"))
    try {
      const cwd = join(root, "work")
      const state = join(root, "state")
      await mkdir(cwd, { recursive: true })
      await mkdir(state, { recursive: true })
      const request: RunnerRequest = {
        opencode_bin: "/usr/bin/true",
        model: "fixture/model",
        cwd,
        state_root: state,
        sandbox: { mode: "bubblewrap", network: "allow", bubblewrap_bin: "/usr/bin/bwrap" },
      }
      const command = await sandboxedServerCommand(request, state)
      expect(
        command.findIndex(
          (value, index) => value === "--ro-bind" && command[index + 1] === "/run",
        ),
      ).toBe(-1)
      expect(
        command.findIndex(
          (value, index) => value === "--bind" && command[index + 1] === "/run",
        ),
      ).toBe(-1)
      if ((await lstat("/etc/resolv.conf")).isSymbolicLink()) {
        const source = await realpath("/etc/resolv.conf")
        const target = resolve("/etc", await readlink("/etc/resolv.conf"))
        expect(
          command.findIndex(
            (value, index) => value === "--ro-bind" && command[index + 1] === source && command[index + 2] === target,
          ),
        ).toBeGreaterThan(-1)
        expect(
          command.findIndex(
            (value, index) => value === "--ro-bind" && command[index + 1] === dirname(target) && command[index + 2] === dirname(target),
          ),
        ).toBe(-1)
        expect(
          command
            .flatMap((value, index) =>
              value === "--ro-bind" && command[index + 1]?.startsWith("/run/")
                ? [[command[index + 1], command[index + 2]]]
                : [],
            ),
        ).toEqual([[source, target]])
      }
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  test("orders read-only carve-outs after writable parents", async () => {
    const root = await mkdtemp(join(tmpdir(), "metalanguage-opencode-mounts-"))
    const cwd = join(root, "work")
    const state = join(root, "state")
    const shared = join(root, "shared")
    const batch = join(root, "archive_worktrees", "batch")
    const own = join(batch, "rollout_000")
    for (const path of [cwd, state, shared, own]) {
      await mkdir(path, { recursive: true })
    }
    const readme = join(cwd, "README.md")
    const benchmark = join(shared, "BENCHMARK.md")
    await writeFile(readme, "contract\n")
    await writeFile(benchmark, "benchmark\n")
    const request: RunnerRequest = {
      opencode_bin: "/usr/bin/true",
      model: "fixture/model",
      cwd,
      state_root: state,
      sandbox: {
        mode: "bubblewrap",
        network: "allow",
        bubblewrap_bin: "/usr/bin/bwrap",
        read_only_roots: [readme, benchmark, batch],
        writable_roots: [own, shared],
      },
    }
    const command = await sandboxedServerCommand(request, state)
    const mountIndex = (flag: string, path: string): number =>
      command.findIndex(
        (value, index) => value === flag && command[index + 1] === path && command[index + 2] === path,
      )
    expect(mountIndex("--bind", cwd)).toBeGreaterThan(-1)
    expect(mountIndex("--ro-bind", readme)).toBeGreaterThan(mountIndex("--bind", cwd))
    expect(mountIndex("--ro-bind", batch)).toBeGreaterThan(-1)
    expect(mountIndex("--bind", own)).toBeGreaterThan(mountIndex("--ro-bind", batch))
    expect(mountIndex("--ro-bind", benchmark)).toBeGreaterThan(mountIndex("--bind", shared))
  })

  test("builds exact offline custom provider configs for chat and responses modes", () => {
    const base = {
      provider_id: "fixture",
      provider_name: "Fixture Provider",
      base_url: "http://127.0.0.1:8000/v1",
      api_key_env: "FIXTURE_API_KEY",
      headers: { "X-Fixture": "FIXTURE_HEADER" },
      model_id: "model-one",
      limits: { context: 8192, output: 1024 },
    }
    const chat = customProviderConfig("fixture/model-one", {
      ...base,
      npm: "@ai-sdk/openai-compatible",
      api_mode: "chat_completions",
    })
    expect(chat).toEqual({
      fixture: {
        npm: "@ai-sdk/openai-compatible",
        name: "Fixture Provider",
        options: {
          baseURL: "http://127.0.0.1:8000/v1",
          apiKey: "{env:FIXTURE_API_KEY}",
          headers: { "X-Fixture": "{env:FIXTURE_HEADER}" },
        },
        models: {
          "model-one": {
            name: "model-one",
            limit: { context: 8192, output: 1024 },
          },
        },
      },
    })
    expect(
      customProviderConfig("fixture/model-one", {
        ...base,
        npm: "@ai-sdk/openai",
        api_mode: "responses",
      }),
    ).toHaveProperty("fixture.npm", "@ai-sdk/openai")
    expect(() =>
      customProviderConfig("other/model-one", {
        ...base,
        npm: "@ai-sdk/openai-compatible",
        api_mode: "chat_completions",
      }),
    ).toThrow("does not match")
    expect(() =>
      customProviderConfig("fixture/model-one", {
        ...base,
        npm: "@ai-sdk/openai",
        api_mode: "chat_completions",
      }),
    ).toThrow("not bundled")
    expect(() =>
      customProviderConfig("fixture/model-one", {
        ...base,
        headers: { "Proxy-Authorization": "FIXTURE_HEADER" },
        npm: "@ai-sdk/openai-compatible",
        api_mode: "chat_completions",
      }),
    ).toThrow("header configuration")
    expect(() =>
      customProviderConfig("fixture/model-one", {
        ...base,
        limits: { context: 100_000_001, output: 1024 },
        npm: "@ai-sdk/openai-compatible",
        api_mode: "chat_completions",
      }),
    ).toThrow("limits")
  })

  test("translates MCP names, native config, permissions, and sensitive selectors", () => {
    const translated = translateMcp(
      { supergpqa: mcpServer() },
      [{ server: "supergpqa", tool: "submit_solution" }],
    )
    expect(translated.servers[0]?.configName).toBe("mcp__supergpqa_")
    expect(translated.servers[0]?.expectedToolIds).toEqual(
      new Set(["mcp__supergpqa__submit_solution"]),
    )
    expect(translated.sensitiveToolIds).toEqual(new Set(["mcp__supergpqa__submit_solution"]))
    expect(translated.config.mcp__supergpqa_).toMatchObject({
      type: "local",
      command: ["/usr/bin/python3", "-m", "utils.supergpqa_mcp"],
      cwd: "/workspace",
      timeout: 31_000,
    })
    expect(translated.permissionRules).toContainEqual({
      permission: "mcp__supergpqa__*",
      pattern: "*",
      action: "deny",
    })
    expect(translated.permissionRules).toContainEqual({
      permission: "mcp__supergpqa__submit_solution",
      pattern: "*",
      action: "allow",
    })
    expect(translated.permissionRules).toContainEqual({
      permission: "bash",
      pattern: "*",
      action: "deny",
    })
    expect(translated.permissionRules).toContainEqual({
      permission: "external_directory",
      pattern: "*",
      action: "deny",
    })
  })

  test("preserves ARC native MCP naming and image-capable transport", () => {
    const server = mcpServer()
    server.enabled_tools = ["RESET", "ACTION1", "ACTION2"]
    const translated = translateMcp({ arc_agi: server }, [])
    expect(translated.servers[0]?.expectedToolIds).toEqual(
      new Set(["mcp__arc_agi__RESET", "mcp__arc_agi__ACTION1", "mcp__arc_agi__ACTION2"]),
    )
    expect(translated.config.mcp__arc_agi_).toHaveProperty("type", "local")
  })

  test("fails closed for invalid allowlists, approvals, and selectors", () => {
    const empty = mcpServer()
    empty.enabled_tools = []
    expect(() => translateMcp({ benchmark: empty }, [])).toThrow("non-empty enabled_tools")

    const prompt = mcpServer()
    prompt.default_tools_approval_mode = "prompt"
    expect(() => translateMcp({ benchmark: prompt }, [])).toThrow("approval_mode=approve")

    expect(() =>
      translateMcp({ benchmark: mcpServer() }, [{ server: "benchmark", tool: "missing" }]),
    ).toThrow("unconfigured or disabled")
  })

  test("rejects malformed SSE JSON", () => {
    const decoder = new SseDecoder()
    expect(() => decoder.push(new TextEncoder().encode("event: message\ndata: {not-json}\n\n"))).toThrow(
      "malformed OpenCode SSE JSON",
    )
  })

  test("redacts sensitive tools and retains parent text", () => {
    const tool = "mcp__supergpqa__submit_solution"
    const normalizer = new EventNormalizer("ses_test", new Set([tool]))
    const events = [
      { type: "session.status", properties: { sessionID: "ses_test", status: { type: "busy" } } },
      {
        type: "message.updated",
        properties: { info: { id: "msg_parent", sessionID: "ses_test", role: "assistant" } },
      },
      {
        type: "message.part.updated",
        properties: {
          part: {
            id: "part_tool",
            sessionID: "ses_test",
            type: "tool",
            tool,
            state: { status: "running", input: { answer: "SECRET_ARGUMENT" } },
          },
        },
      },
      {
        type: "message.part.updated",
        properties: {
          part: {
            id: "part_tool",
            sessionID: "ses_test",
            type: "tool",
            tool,
            state: {
              status: "completed",
              input: { answer: "SECRET_ARGUMENT" },
              output: "SECRET_RESULT",
            },
          },
        },
      },
      {
        type: "message.part.updated",
        properties: {
          part: {
            id: "part_text",
            messageID: "msg_parent",
            sessionID: "ses_test",
            type: "text",
            text: "parent continued",
            time: { start: 1, end: 2 },
          },
        },
      },
      { type: "session.status", properties: { sessionID: "ses_test", status: { type: "idle" } } },
    ]
    const durable: unknown[] = []
    let terminal = "continue"
    for (const event of events) {
      const reduced = normalizer.handle(event)
      durable.push(...reduced.events)
      terminal = reduced.terminal
    }
    const logged = JSON.stringify(durable)
    expect(logged).not.toContain("SECRET_ARGUMENT")
    expect(logged).not.toContain("SECRET_RESULT")
    expect(logged).toContain("redacted")
    expect(normalizer.finalText()).toBe("parent continued")
    expect(terminal).toBe("idle")

  })

  test("ignores an initial idle status until the submitted turn becomes busy", () => {
    const normalizer = new EventNormalizer("ses_test", new Set())
    expect(
      normalizer.handle({
        type: "session.status",
        properties: { sessionID: "ses_test", status: { type: "idle" } },
      }).terminal,
    ).toBe("continue")
    expect(
      normalizer.handle({
        type: "session.status",
        properties: { sessionID: "ses_test", status: { type: "busy" } },
      }),
    ).toEqual({ events: [{ event: "turn_started" }], terminal: "continue" })
    expect(
      normalizer.handle({
        type: "session.status",
        properties: { sessionID: "ses_test", status: { type: "idle" } },
      }).terminal,
    ).toBe("idle")
  })

  test("disables history compaction for the managed runner", () => {
    const config = opencodeConfig(
      {
        opencode_bin: "/usr/bin/true",
        model: "fixture/model",
        cwd: "/workspace",
        state_root: "/state",
      },
      translateMcp({}, []),
    )
    expect(config.compaction).toEqual({ auto: false, prune: false })
  })

  test("treats only provider context overflow as a normal context boundary", () => {
    const normalizer = new EventNormalizer("ses_test", new Set(), ["PRIVATE_CONTEXT_VALUE"])
    normalizer.handle({
      type: "message.updated",
      properties: { info: { id: "assistant", sessionID: "ses_test", role: "assistant" } },
    })
    normalizer.handle({
      type: "message.part.updated",
      properties: {
        part: {
          id: "text",
          messageID: "assistant",
          sessionID: "ses_test",
          type: "text",
          text: "useful partial answer",
        },
      },
    })
    const exhausted = normalizer.handle({
      type: "session.error",
      properties: {
        sessionID: "ses_test",
        error: {
          name: "ContextOverflowError",
          data: {
            message: "context limit reached PRIVATE_CONTEXT_VALUE",
            statusCode: 413,
            isRetryable: false,
          },
        },
      },
    })
    expect(exhausted.terminal).toBe("context_exhausted")
    expect(exhausted.events).toEqual([
      {
        event: "context_exhausted",
        stop_reason: "context_exhausted",
        boundary_source: "provider_context_window_exceeded",
        final_text: "useful partial answer",
        context_provider_error_code: "ContextOverflowError",
        context_provider_error_message: "context limit reached [REDACTED]",
        context_provider_error_http_status: 413,
        context_provider_error_retryable: false,
      },
    ])
    expect(normalizer.error).toBeUndefined()

    const unrelated = new EventNormalizer("ses_test", new Set()).handle({
      type: "session.error",
      properties: {
        sessionID: "ses_test",
        error: { name: "APIError", data: { message: "provider unavailable" } },
      },
    })
    expect(unrelated.terminal).toBe("error")
    expect(unrelated.events[0]?.event).toBe("error")
  })

  test("fails closed on an unexpected compaction event", () => {
    const compacted = new EventNormalizer("ses_test", new Set()).handle({
      type: "session.compacted",
      properties: { sessionID: "ses_test" },
    })
    expect(compacted).toEqual({
      events: [{
        event: "error",
        error_code: "unexpected_compaction",
        error_message: "OpenCode compacted context despite compaction being disabled",
      }],
      terminal: "error",
    })

    const part = new EventNormalizer("ses_test", new Set()).handle({
      type: "message.part.updated",
      properties: { part: { id: "compact", sessionID: "ses_test", type: "compaction" } },
    })
    expect(part.terminal).toBe("error")
    expect(part.events[0]?.error_code).toBe("unexpected_compaction")
  })

  test("normalizes provider errors and redacts image payloads", () => {
    const normalizer = new EventNormalizer("ses_test", new Set())
    const attachment = normalizer.handle({
      type: "message.part.updated",
      properties: {
        part: {
          id: "image",
          sessionID: "ses_test",
          type: "file",
          mime: "image/png",
          url: "data:image/png;base64,SECRET",
        },
      },
    })
    expect(JSON.stringify(attachment.events)).not.toContain("SECRET")
    const failed = normalizer.handle({
      type: "session.error",
      properties: {
        sessionID: "ses_test",
        error: { name: "ProviderAuthError", data: { message: "authentication failed sk-PRIVATE" } },
      },
    })
    expect(failed.terminal).toBe("error")
    expect(normalizer.error).toEqual({
      error_code: "ProviderAuthError",
      error_message: "authentication failed [REDACTED]",
    })
    expect(JSON.stringify(failed.events)).not.toContain("PRIVATE")

    const adversarial = normalizer.handle({
      type: "session.error",
      properties: {
        sessionID: "ses_test",
        error: { name: `Provider\nBearer sk-PRIVATE-${"💣".repeat(300)}` },
      },
    })
    const code = adversarial.events[0]?.error_code
    expect(typeof code).toBe("string")
    expect(String(code).length).toBeLessThanOrEqual(128)
    expect(String(code)).toMatch(/^[a-zA-Z0-9_.-]+$/)
    expect(JSON.stringify(adversarial.events)).not.toContain("PRIVATE")
    expect(safeErrorCode(42)).toBe("unknown")
  })

  test("preserves only bounded sanitized provider diagnostics", () => {
    const normalizer = new EventNormalizer("ses_test", new Set(), ["OPAQUE_PROVIDER_VALUE_123"])
    const failed = normalizer.handle({
      type: "session.error",
      properties: {
        sessionID: "ses_test",
        error: {
          name: "APIError",
          data: {
            message:
              "fetch failed\ngetaddrinfo EAI_AGAIN api.openrouter.ai\u0000 " +
              "Bearer bearer-secret-value OPENROUTER_API_KEY=sk-PRIVATE-KEY " +
              "Authorization: Basic PRIVATE_BASIC \"token\":\"PRIVATE_JSON_TOKEN\" " +
              "OPAQUE_PROVIDER_VALUE_123 " +
              "https://example.test/provider?api_key=PRIVATE_QUERY",
            statusCode: 503,
            isRetryable: true,
            responseHeaders: { authorization: "Bearer PRIVATE_HEADER" },
            responseBody: "PRIVATE_RESPONSE_BODY",
            metadata: { request: "PRIVATE_REQUEST_PAYLOAD" },
          },
          stack: "PRIVATE_STACK",
        },
      },
    })
    expect(failed.terminal).toBe("error")
    expect(failed.events[0]).toEqual({ event: "error", ...normalizer.error })
    expect(Object.keys(failed.events[0] ?? {}).sort()).toEqual([
      "error_code",
      "error_http_status",
      "error_message",
      "error_retryable",
      "event",
    ])
    const serialized = JSON.stringify(failed.events)
    expect(serialized).toContain("getaddrinfo EAI_AGAIN api.openrouter.ai")
    expect(serialized).toContain("https://example.test/provider")
    expect(serialized).not.toContain("api_key=")
    expect(serialized).toContain("[REDACTED]")
    expect(serialized).not.toContain("PRIVATE")
    expect(serialized).not.toContain("responseHeaders")
    expect(serialized).not.toContain("responseBody")
    expect(serialized).not.toContain("metadata")
    expect(serialized).not.toContain("stack")
    expect(normalizer.error?.error_message).not.toMatch(/[\u0000-\u001f\u007f-\u009f]/)
    expect(normalizer.error?.error_http_status).toBe(503)
    expect(normalizer.error?.error_retryable).toBe(true)

    const long = new EventNormalizer("ses_long", new Set())
    long.handle({
      type: "session.error",
      properties: {
        sessionID: "ses_long",
        error: { name: "APIError", data: { message: "x".repeat(700), isRetryable: false } },
      },
    })
    expect([...(long.error?.error_message ?? "")].length).toBe(512)
    expect(long.error?.error_message.endsWith("…")).toBe(true)

    const fallback = new EventNormalizer("ses_fallback", new Set())
    const fallbackEvent = fallback.handle({
      type: "session.error",
      properties: {
        sessionID: "ses_fallback",
        error: {
          name: "APIError",
          data: {
            statusCode: "503",
            isRetryable: "true",
            responseBody: { message: "PRIVATE_NESTED_MESSAGE" },
          },
        },
      },
    })
    expect(fallbackEvent.events).toEqual([
      {
        event: "error",
        error_code: "APIError",
        error_message: "OpenCode request failed (APIError)",
      },
    ])
    expect(JSON.stringify(fallbackEvent.events)).not.toContain("PRIVATE")
  })

  test("selects only the final assistant message in production event order", () => {
    const normalizer = new EventNormalizer("ses_test", new Set())
    const events = [
      { type: "message.updated", properties: { info: { id: "u1", sessionID: "ses_test", role: "user" } } },
      {
        type: "message.part.updated",
        properties: { part: { id: "up", messageID: "u1", sessionID: "ses_test", type: "text", text: "USER" } },
      },
      {
        type: "message.updated",
        properties: { info: { id: "a1", sessionID: "ses_test", role: "assistant" } },
      },
      {
        type: "message.part.updated",
        properties: {
          part: {
            id: "ap1",
            messageID: "a1",
            sessionID: "ses_test",
            type: "text",
            text: "INTERMEDIATE",
            time: { start: 1, end: 2 },
          },
        },
      },
      { type: "session.status", properties: { sessionID: "ses_test", status: { type: "retry" } } },
      {
        type: "message.updated",
        properties: { info: { id: "a2", sessionID: "ses_test", role: "assistant" } },
      },
      {
        type: "message.part.updated",
        properties: {
          part: {
            id: "ap2",
            messageID: "a2",
            sessionID: "ses_test",
            type: "text",
            text: "FINAL",
            time: { start: 3, end: 4 },
          },
        },
      },
    ]
    for (const event of events) normalizer.handle(event)
    expect(normalizer.finalText()).toBe("FINAL")
  })

  test("selects only the completed assistant response parented by the submitted user message", () => {
    const messages = [
      {
        info: { id: "u1", role: "user" },
        parts: [{ id: "up", messageID: "u1", type: "text", text: "USER" }],
      },
      {
        info: { id: "a1", role: "assistant", parentID: "u1", finish: "tool-calls" },
        parts: [{ id: "ap1", messageID: "a1", type: "text", text: "INTERMEDIATE" }],
      },
      {
        info: { id: "a2", role: "assistant", parentID: "other", finish: "stop" },
        parts: [{ id: "wrong", messageID: "a2", type: "text", text: "WRONG TURN" }],
      },
      {
        info: { id: "a3", role: "assistant", parentID: "u1", finish: "stop" },
        parts: [{ id: "ap3", messageID: "a3", type: "text", text: "FINAL" }],
      },
    ]
    expect(finalAssistantText(messages as never, "u1")).toBe("FINAL")
    expect(finalAssistantText(messages as never, "missing")).toBeUndefined()
    expect(finalAssistantText(messages.slice(0, 3) as never, "u1")).toBeUndefined()
    expect(
      finalAssistantText(
        [
          ...messages,
          {
            info: { id: "a4", role: "assistant", parentID: "other", finish: "stop" },
            parts: [{ id: "tool-final", messageID: "a4", type: "tool" }],
          },
        ] as never,
        "u1",
      ),
    ).toBe("FINAL")
  })

  test("malformed SSE errors and generic scrubber do not retain secrets", () => {
    const decoder = new SseDecoder()
    let message = ""
    try {
      decoder.push(
        new TextEncoder().encode('data: {"credential":"sk-PRIVATE-MALFORMED"\n\n'),
      )
    } catch (error) {
      message = String(error)
    }
    expect(message).toContain("malformed OpenCode SSE JSON")
    expect(message).not.toContain("PRIVATE")
    const unknown = new EventNormalizer("ses_test", new Set()).handle({
      type: "future.event",
      properties: { secret: "sk-PRIVATE-UNKNOWN" },
    })
    expect(unknown).toEqual({ events: [], terminal: "continue" })
  })

  test("config-scoped sources expose exact tool and system hooks", () => {
    expect(TOOL_SOURCE).toContain("spawn_child")
    expect(TOOL_SOURCE).toContain("context.abort")
    expect(TOOL_SOURCE).toContain("METALANGUAGE_SPAWN_CHILD_ENDPOINT")
    expect(TOOL_SOURCE).not.toContain("METALANGUAGE_OPENCODE_WORKER_SCRIPT")
    expect(SYSTEM_PLUGIN_SOURCE).toContain("experimental.chat.system.transform")
    expect(SYSTEM_PLUGIN_SOURCE).toContain("output.system.splice")
    expect(SYSTEM_PLUGIN_SOURCE).toContain('"tool.execute.before"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain('"tool.execute.after"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain("METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT")
    expect(SYSTEM_PLUGIN_SOURCE).not.toContain("UserPromptSubmit")
    const configuredPlugin = systemPluginSource({
      endpoint: "http://127.0.0.1:12345/directory-agents",
      token: "private-directory-token",
    })
    expect(configuredPlugin).toContain('const endpoint = "http://127.0.0.1:12345/directory-agents"')
    expect(configuredPlugin).toContain('const token = "private-directory-token"')
    expect(configuredPlugin).not.toContain(
      "const endpoint = process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT",
    )
    expect(configuredPlugin).not.toContain(
      "const token = process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN",
    )
    expect(() => new Function(SYSTEM_PLUGIN_SOURCE.replace("export default", "return"))).not.toThrow()
    expect(SYSTEM_PLUGIN_SOURCE).toContain('"shell.env"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain("OPENCODE_AUTH_CONTENT")
  })

  test("initial context shares the system field with an exact user prompt", () => {
    const request: RunnerRequest = {
      opencode_bin: "/usr/bin/true",
      model: "fixture/model",
      cwd: "/workspace",
      state_root: "/state",
      initial_user_text: "Begin.",
      system_instructions: ".",
      initial_system_context: "<CONTEXT>\nroot\n</CONTEXT>",
    }
    expect(request.initial_user_text).toBe("Begin.")
    expect(initialSystemInstructions(request)).toBe(
      ".\n\n<CONTEXT>\nroot\n</CONTEXT>",
    )
  })
})

describe("directory AGENTS supervisor bridge", () => {
  test("returns exact shell-transition context through the authenticated callback", async () => {
    const root = await mkdtemp(join(tmpdir(), "metalanguage-directory-agents-"))
    const work = join(root, "work")
    const project = join(work, "archives", "project")
    const other = join(work, "other")
    const control = join(root, "control")
    await mkdir(project, { recursive: true })
    await mkdir(other, { recursive: true })
    await mkdir(control, { recursive: true })
    await writeFile(join(work, "AGENTS.md"), "OpenCode root context\n")
    await writeFile(join(project, "AGENTS.md"), "OpenCode project context\n")
    await writeFile(join(other, "AGENTS.md"), "OpenCode other-tool context\n")
    const contextPath = join(control, "continuation_context.json")
    await writeFile(
      contextPath,
      JSON.stringify({
        worker_backend: "opencode",
        workdir: work,
        shared_archives_root: join(work, "archives"),
      }),
    )
    const hook = resolve(import.meta.dir, "../../utils/directory_agents_hook.py")
    const command = ["python3", hook, contextPath]
    const callback = await startDirectoryAgentsCallback(command)
    try {
      const unauthorized = await fetch(callback.endpoint, {
        method: "POST",
        headers: { authorization: "Bearer wrong" },
        body: "{}",
      })
      expect(unauthorized.status).toBe(401)
      const response = await fetch(callback.endpoint, {
        method: "POST",
        headers: {
          authorization: `Bearer ${callback.token}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          hook_event_name: "PostToolUse",
          tool_name: "bash",
          tool_input: { command: "cd archives/project && pwd" },
          metalanguage_shell_transitions_only: true,
        }),
      })
      expect(response.status).toBe(200)
      expect(await response.json()).toMatchObject({
        additional_context: expect.stringContaining("OpenCode project context"),
        defer: false,
      })
      await rm(join(control, "directory_agents_seen"), { force: true })
      const rootDigest = new Bun.CryptoHasher("sha256")
        .update("OpenCode root context\n")
        .digest("hex")
      await writeFile(
        join(control, "directory_agents_seen"),
        `${join(work, "AGENTS.md")}\t${rootDigest}\tinitial\n`,
      )
      const priorEndpoint = process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT
      const priorToken = process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN
      const priorInstructions = process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS
      try {
        process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT = callback.endpoint
        process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN = callback.token
        process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS =
          "exact instructions\n\n<CONTEXT>\nOpenCode root context\n</CONTEXT>"
        const pluginFactory = new Function(
          SYSTEM_PLUGIN_SOURCE.replace("export default", "return"),
        )()
        const plugin = await pluginFactory()
        const shellEnvironment = { env: {} as Record<string, string> }
        await plugin["shell.env"]({}, shellEnvironment)
        expect(shellEnvironment.env).not.toHaveProperty("METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT")
        expect(shellEnvironment.env).not.toHaveProperty("METALANGUAGE_DIRECTORY_AGENTS_TOKEN")
        const args = { command: "cd archives/project && pwd" }
        const identity = { tool: "bash", sessionID: "session-test", callID: "call-test" }
        const toolOutput = {
          title: "shell",
          output: "model-visible",
          metadata: { exit: 0 },
        }
        const initialOutput = { system: ["provider default"] }
        await plugin["experimental.chat.system.transform"](
          { sessionID: "session-test" },
          initialOutput,
        )
        expect(initialOutput.system).toEqual([
          "exact instructions\n\n<CONTEXT>\nOpenCode root context\n</CONTEXT>",
        ])
        await expect(
          plugin["tool.execute.before"](identity, { args }),
        ).rejects.toThrow("Local context activated; tool was not executed.")
        expect(toolOutput).toEqual({
          title: "shell",
          output: "model-visible",
          metadata: { exit: 0 },
        })
        const output = { system: ["provider default"] }
        await plugin["experimental.chat.system.transform"](
          { sessionID: "session-test" },
          output,
        )
        expect(output.system).toEqual([
          "exact instructions\n\n<CONTEXT>\nOpenCode root context\n</CONTEXT>",
          expect.stringContaining("OpenCode project context"),
        ])
        await expect(plugin["tool.execute.before"](identity, { args })).resolves.toBeUndefined()
        await plugin["tool.execute.after"]({ ...identity, args }, toolOutput)
        await expect(
          plugin["tool.execute.before"](
            { tool: "read_file", sessionID: "session-test", callID: "call-read" },
            { args: { workdir: other } },
          ),
        ).rejects.toThrow("Local context activated; tool was not executed.")
        const otherOutput = { system: ["provider default"] }
        await plugin["experimental.chat.system.transform"](
          { sessionID: "session-test" },
          otherOutput,
        )
        expect(otherOutput.system).toHaveLength(2)
        expect(otherOutput.system[0]).toContain("exact instructions")
        expect(otherOutput.system[0]).toContain("OpenCode root context")
        expect(otherOutput.system[1]).toContain("OpenCode project context")
        expect(otherOutput.system[1]).toContain("OpenCode other-tool context")
      } finally {
        if (priorEndpoint === undefined) delete process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT
        else process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT = priorEndpoint
        if (priorToken === undefined) delete process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN
        else process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN = priorToken
        if (priorInstructions === undefined) delete process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS
        else process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS = priorInstructions
      }
      expect(
        await runDirectoryAgentsHandler(command, {
          hook_event_name: "UserPromptSubmit",
        }),
      ).toEqual({ additional_context: "", defer: false })
      expect(
        await runDirectoryAgentsHandler(command, {
          hook_event_name: "PostToolUse",
          tool_name: "bash",
          tool_input: { command: "printf 'cd archives/project'" },
          metalanguage_shell_transitions_only: true,
        }),
      ).toEqual({ additional_context: "", defer: false })
    } finally {
      callback.stop()
      await rm(root, { recursive: true, force: true })
    }
  })
})

describe("spawn_child supervisor bridge", () => {
  test("host callback rejects unauthorized and oversized spawn requests", async () => {
    const callback = await startSpawnCallback([
      "python3",
      "-c",
      "import json,sys; print(json.dumps(json.loads(sys.stdin.read())))",
    ])
    try {
      const unauthorized = await fetch(callback.endpoint, {
        method: "POST",
        headers: { authorization: "Bearer wrong" },
        body: "{}",
      })
      expect(unauthorized.status).toBe(401)
      const oversized = await fetch(callback.endpoint, {
        method: "POST",
        headers: {
          authorization: `Bearer ${callback.token}`,
        },
        body: JSON.stringify({
          tool: "spawn_child",
          namespace: null,
          call_id: "oversized",
          arguments: { prompt: "x".repeat(65 * 1024), workspace_dir: "child" },
        }),
      })
      expect(oversized.status).toBe(413)
    } finally {
      callback.stop()
    }
  })

  test("preserves success and retry responses", async () => {
    for (const response of [
      { success: true, child_spawned: true, parent_continues: true },
      { success: false, child_spawned: false, parent_continues: true, retryable: true },
    ]) {
      const script = `import json; print(${JSON.stringify(JSON.stringify(response))})`
      const output = await runHandler(
        ["python3", "-c", script],
        { tool: "spawn_child", arguments: { prompt: "p", workspace_dir: "w" } },
      )
      expect(output).toEqual(response)
    }
  })

  test("returns structured retryable crash, malformed, and timeout failures", async () => {
    const cases = [
      {
        command: ["python3", "-c", "raise SystemExit(7)"],
        timeout: 1_000,
        code: "spawn_child_handler_crashed",
      },
      {
        command: ["python3", "-c", "print('not-json')"],
        timeout: 1_000,
        code: "spawn_child_handler_malformed_response",
      },
      {
        command: ["python3", "-c", "import time; time.sleep(30)"],
        timeout: 25,
        code: "spawn_child_handler_timeout",
      },
    ]
    for (const item of cases) {
      const result = await runHandler(
        item.command,
        { tool: "spawn_child", arguments: {} },
        item.timeout,
      )
      expect(result).toMatchObject({
        success: false,
        child_spawned: false,
        parent_continues: true,
        retryable: true,
        error_code: item.code,
      })
    }
  })

  test("callback keeps handler failures on HTTP 200 for model retries", async () => {
    const callback = await startSpawnCallback(
      ["python3", "-c", "import time; time.sleep(30)"],
      25,
    )
    try {
      const response = await fetch(callback.endpoint, {
        method: "POST",
        headers: {
          authorization: `Bearer ${callback.token}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ tool: "spawn_child", arguments: {} }),
      })
      expect(response.status).toBe(200)
      expect(await response.json()).toMatchObject({
        parent_continues: true,
        retryable: true,
        error_code: "spawn_child_handler_timeout",
      })
    } finally {
      callback.stop()
    }
  })
})

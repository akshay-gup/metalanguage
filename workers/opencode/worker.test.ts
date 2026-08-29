import { describe, expect, test } from "bun:test"
import { mkdir, mkdtemp, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

import {
  EventNormalizer,
  SseDecoder,
  customProviderConfig,
  safeErrorCode,
  translateMcp,
  type McpServerInput,
  type RunnerRequest,
} from "./protocol.ts"
import { finalAssistantText, sandboxedServerCommand, startSpawnCallback } from "./worker.ts"
import { runHandler, SYSTEM_PLUGIN_SOURCE, TOOL_SOURCE } from "./spawn_bridge.ts"

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
  test("orders read-only carve-outs after writable parents", async () => {
    const root = await mkdtemp(join(tmpdir(), "metalanguage-opencode-mounts-"))
    const cwd = join(root, "work")
    const state = join(root, "state")
    const shared = join(root, "shared")
    const batch = join(root, "archive_worktrees", "batch")
    const own = join(batch, "rollout_000")
    for (const path of [cwd, state, shared, own, join(batch, "rollout_001")]) {
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
    expect(normalizer.error).toEqual([
      "ProviderAuthError",
      "OpenCode request failed (ProviderAuthError)",
    ])
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
    expect(SYSTEM_PLUGIN_SOURCE).toContain('"shell.env"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain("OPENCODE_AUTH_CONTENT")
  })
})

describe("spawn_child supervisor bridge", () => {
  test("host callback rejects unauthorized and oversized control requests", async () => {
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
        body: "x".repeat(65 * 1024),
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

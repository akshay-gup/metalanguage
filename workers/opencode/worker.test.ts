import { describe, expect, test } from "bun:test"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { pathToFileURL } from "node:url"

import {
  EventNormalizer,
  SseDecoder,
  customProviderConfig,
  safeErrorCode,
  translateMcp,
  type McpServerInput,
} from "./protocol.ts"
import { finalAssistantText, startSpawnCallback } from "./worker.ts"
import {
  runHandler,
  SEND_MESSAGE_TOOL_SOURCE,
  SYSTEM_PLUGIN_SOURCE,
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

  test("redacts message tool arguments and results without MCP selectors", () => {
    for (const tool of ["send_message"]) {
      const normalizer = new EventNormalizer("ses_test", new Set())
      const begin = normalizer.handle({
        type: "message.part.updated",
        properties: {
          part: {
            id: `peer_${tool}`,
            sessionID: "ses_test",
            type: "tool",
            tool,
            state: { status: "running", input: { message: "SECRET_PEER_MESSAGE" } },
          },
        },
      })
      const end = normalizer.handle({
        type: "message.part.updated",
        properties: {
          part: {
            id: `peer_${tool}`,
            sessionID: "ses_test",
            type: "tool",
            tool,
            state: { status: "completed", output: "SECRET_PEER_RESULT" },
          },
        },
      })
      const durable = JSON.stringify([...begin.events, ...end.events])
      expect(durable).not.toContain("SECRET_PEER")
      expect(durable).toContain("redacted")
    }
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
    expect(SEND_MESSAGE_TOOL_SOURCE).toContain('tool: "send_message"')
    expect(SEND_MESSAGE_TOOL_SOURCE).toContain("context.abort")
    expect(SEND_MESSAGE_TOOL_SOURCE).not.toContain("action:")
    expect(SEND_MESSAGE_TOOL_SOURCE).toContain("receiver")
    expect(SEND_MESSAGE_TOOL_SOURCE).toContain(
      "Send a bounded non-empty UTF-8 direct message to a named peer in the current batch. The receiver must exactly match a peer name in runtime.md. Delivery is automatic at a subsequent supported inference boundary.",
    )
    for (const prescriptive of [
      "claiming a direction",
      "sharing a result",
      "requesting verification",
      "warning of a conflict",
      "divide complementary",
      "critique or verify",
      "synthesize results",
    ]) expect(SEND_MESSAGE_TOOL_SOURCE).not.toContain(prescriptive)
    expect(SEND_MESSAGE_TOOL_SOURCE).not.toContain("topic")
    expect(SEND_MESSAGE_TOOL_SOURCE).not.toContain("recipient_rollout_index")
    expect(SYSTEM_PLUGIN_SOURCE).toContain("experimental.chat.system.transform")
    expect(SYSTEM_PLUGIN_SOURCE).toContain("experimental.chat.messages.transform")
    expect(SYSTEM_PLUGIN_SOURCE).toContain('"chat.params"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain('peerRequest("_peer_delivery_prepare"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain('peerRequest("_peer_delivery_ack"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain('input.toolID === "send_message"')
    expect(SYSTEM_PLUGIN_SOURCE).not.toContain('input.toolID === "read_messages"')
    expect(SYSTEM_PLUGIN_SOURCE).not.toContain('toolID === "peer_communication"')
    expect(SYSTEM_PLUGIN_SOURCE).not.toContain('required: ["action"]')
    expect(SYSTEM_PLUGIN_SOURCE).toContain("output.system.splice")
    expect(SYSTEM_PLUGIN_SOURCE).toContain('"shell.env"')
    expect(SYSTEM_PLUGIN_SOURCE).toContain("OPENCODE_AUTH_CONTENT")
  })

  test("config-scoped pre-sampling hook injects and acknowledges one durable bundle", async () => {
    const calls: Array<Record<string, unknown>> = []
    const token = "test-peer-token"
    let prepared = false
    const server = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      async fetch(request) {
        expect(request.headers.get("authorization")).toBe(`Bearer ${token}`)
        const payload = await request.json() as Record<string, unknown>
        calls.push(payload)
        if (payload.tool === "_peer_delivery_prepare" && !prepared) {
          prepared = true
          return Response.json({
            success: true,
            pending: true,
            delivery_id: "lease-9",
            injection: "[UNTRUSTED PEER CONTENT]\nMessage #9 from Alice:\ncheck route",
            message_count: 1,
            through_id: 9,
            has_more: false,
          })
        }
        if (payload.tool === "_peer_delivery_prepare") {
          return Response.json({ success: true, pending: false, message_count: 0, has_more: false })
        }
        return Response.json({ success: true, committed: true })
      },
    })
    const oldEndpoint = process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT
    const oldToken = process.env.METALANGUAGE_SPAWN_CHILD_TOKEN
    const oldEnabled = process.env.METALANGUAGE_PEER_COMMUNICATION_ENABLED
    process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT = `http://127.0.0.1:${server.port}/spawn-child`
    process.env.METALANGUAGE_SPAWN_CHILD_TOKEN = token
    process.env.METALANGUAGE_PEER_COMMUNICATION_ENABLED = "1"
    const pluginRoot = await mkdtemp(join(tmpdir(), "metalanguage-plugin-test-"))
    try {
      const pluginPath = join(pluginRoot, "plugin.js")
      await writeFile(pluginPath, SYSTEM_PLUGIN_SOURCE)
      const factory = (await import(pathToFileURL(pluginPath).href)).default
      const plugin = await factory()
      const messages = [{
        info: {
          id: "msg_original",
          sessionID: "ses_test",
          role: "user",
          time: { created: 1 },
          agent: "build",
          model: { providerID: "fixture", modelID: "model" },
        },
        parts: [{ id: "prt_original", sessionID: "ses_test", messageID: "msg_original", type: "text", text: "start" }],
      }]
      await plugin["experimental.chat.messages.transform"]({}, { messages })
      expect(messages).toHaveLength(2)
      expect(messages[1]?.parts[0]?.text).toContain("Message #9 from Alice")
      expect((messages[1]?.parts[0] as Record<string, unknown> | undefined)?.synthetic).toBe(true)
      expect(calls.map((call) => call.tool)).toEqual(["_peer_delivery_prepare"])
      await plugin["chat.params"](
        { sessionID: "ses_test", agent: "build", model: {}, provider: {}, message: messages[0]?.info },
        {},
      )
      expect(calls.map((call) => call.tool)).toEqual(["_peer_delivery_prepare", "_peer_delivery_ack"])
      expect(JSON.stringify(calls)).not.toContain("check route")

      await plugin["experimental.chat.messages.transform"]({}, { messages })
      expect(messages).toHaveLength(2)
      expect(calls.map((call) => call.tool)).toEqual([
        "_peer_delivery_prepare",
        "_peer_delivery_ack",
        "_peer_delivery_prepare",
      ])
    } finally {
      if (oldEndpoint === undefined) delete process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT
      else process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT = oldEndpoint
      if (oldToken === undefined) delete process.env.METALANGUAGE_SPAWN_CHILD_TOKEN
      else process.env.METALANGUAGE_SPAWN_CHILD_TOKEN = oldToken
      if (oldEnabled === undefined) delete process.env.METALANGUAGE_PEER_COMMUNICATION_ENABLED
      else process.env.METALANGUAGE_PEER_COMMUNICATION_ENABLED = oldEnabled
      server.stop(true)
      await rm(pluginRoot, { recursive: true, force: true })
    }
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

  test("message and protected delivery callbacks preserve central structured responses", async () => {
    for (const [tool, toolArguments, response] of [
      ["send_message", { message: "finding", receiver: "Alice" }, { success: true, tool: "send_message", id: 7 }],
      ["_peer_delivery_prepare", {}, { success: true, pending: true, delivery_id: "lease-7", injection: "peer", message_count: 1, through_id: 7 }],
      ["_peer_delivery_ack", { delivery_id: "lease-7" }, { success: true, committed: true }],
    ] as const) {
      const script = `import json; print(${JSON.stringify(JSON.stringify(response))})`
      const output = await runHandler(["python3", "-c", script], { tool, arguments: toolArguments })
      expect(output).toEqual(response)
    }
    for (const tool of ["read_messages", "peer_communication"]) {
      const legacy = await runHandler(
        ["python3", "-c", "raise SystemExit('legacy handler must not run')"],
        { tool, arguments: {} },
      )
      expect(legacy).toMatchObject({ success: false, error_code: "unsupported_dynamic_tool" })
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

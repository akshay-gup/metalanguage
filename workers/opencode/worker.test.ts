import { describe, expect, test } from "bun:test"

import {
  EventNormalizer,
  SseDecoder,
  translateMcp,
  type McpServerInput,
} from "./protocol.ts"
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
        error: { name: "ProviderAuthError", data: { message: "authentication failed" } },
      },
    })
    expect(failed.terminal).toBe("error")
    expect(normalizer.error).toEqual(["ProviderAuthError", "authentication failed"])
  })

  test("config-scoped sources expose exact tool and system hooks", () => {
    expect(TOOL_SOURCE).toContain("spawn_child")
    expect(TOOL_SOURCE).toContain("context.abort")
    expect(SYSTEM_PLUGIN_SOURCE).toContain("experimental.chat.system.transform")
    expect(SYSTEM_PLUGIN_SOURCE).toContain("output.system.splice")
  })
})

describe("spawn_child supervisor bridge", () => {
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

  test("reports handler process failure", async () => {
    await expect(
      runHandler(
        ["python3", "-c", "import sys; print('boom', file=sys.stderr); raise SystemExit(7)"],
        { tool: "spawn_child", arguments: {} },
      ),
    ).rejects.toThrow("boom")
  })
})

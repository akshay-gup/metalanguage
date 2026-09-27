import { describe, expect, test } from "bun:test"

import { systemPluginSource } from "./spawn_bridge.ts"

function user(sessionID = "session") {
  return {
    info: {
      id: "begin-" + sessionID,
      sessionID,
      role: "user",
      time: { created: 1 },
      agent: "build",
      model: { providerID: "fixture", modelID: "fixture" },
    },
    parts: [{ type: "text", text: "Begin." }],
  }
}

function exchange(id: string, sessionID = "session", status = "error") {
  return {
    info: { id, sessionID, role: "assistant" },
    parts: [{
      type: "tool",
      callID: id + "-call",
      tool: "bash",
      state: { status, output: "original tool output", error: "Local context activated; tool was not executed." },
    }],
  }
}

type Callback = {
  session_id: string
  hook_event_name: string
  tool_input: { guide?: string; repeat?: boolean }
}

type ProjectedMessage = {
  info: { id: string; sessionID: string; role: string }
  parts: Array<{ text?: string; synthetic?: boolean; metadata?: unknown }>
}

async function fixture(wait?: (payload: Callback) => Promise<void>) {
  const calls: Callback[] = []
  const seen = new Set<string>()
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      const payload = await request.json() as Callback
      calls.push(payload)
      await wait?.(payload)
      const guide = payload.tool_input.guide ?? ""
      const key = payload.session_id + "\n" + guide
      const fresh = !!guide && (!seen.has(key) || payload.tool_input.repeat)
      seen.add(key)
      return Response.json({
        additional_context: fresh ? guide : "",
        defer: fresh && payload.hook_event_name === "PreToolUse",
      })
    },
  })
  const plugin = await new Function(systemPluginSource({
    endpoint: `http://127.0.0.1:${server.port}/directory-agents`,
    token: "fixture-token",
  }).replace("export default", "return"))()()
  return {
    plugin,
    calls,
    stop: () => server.stop(true),
    before: (guide: string, callID = "call", sessionID = "session") => plugin["tool.execute.before"](
      { tool: "bash", sessionID, callID }, { args: { guide } },
    ),
    after: (guide: string, callID = "call", sessionID = "session", repeat = false) => plugin["tool.execute.after"](
      { tool: "bash", sessionID, callID, args: { guide, repeat } }, { output: "unchanged" },
    ),
    project: async (messages: unknown[]) => {
      const output = { messages }
      await plugin["experimental.chat.messages.transform"]({}, output)
      return output.messages as ProjectedMessage[]
    },
  }
}

describe("chronological managed directory context", () => {
  test("pre-gate has no dispatch; user context stays anchored across retries and later inferences", async () => {
    const f = await fixture()
    try {
      let dispatched = 0
      const guide = '<AGENTS_MD path="/A/AGENTS.md">\nguide A\n</AGENTS_MD>'
      const execute = async () => { await f.before(guide); dispatched++ }
      await expect(execute()).rejects.toThrow("tool was not executed")
      const system = { system: ["fixed root"] }
      await f.plugin["experimental.chat.system.transform"]({ sessionID: "session" }, system)
      await expect(execute()).rejects.toThrow("tool was not executed")
      expect(dispatched).toBe(0)
      expect(f.calls).toHaveLength(1)
      expect(system.system.join("\n")).not.toContain("guide A")
      const begin = user()
      const tools = exchange("gate")
      const snapshot = structuredClone([begin, tools])
      const first = await f.project([begin, tools])
      expect(first.map((m) => m.info.role)).toEqual(["user", "assistant", "user"])
      expect(first[2].parts[0].text).toContain("not a new human request")
      expect(first[2].parts[0].text).toContain(guide)
      expect(first[2].parts[0].synthetic).toBe(true)
      expect(first[2].parts[0].metadata).toMatchObject({ metalanguage: { kind: "directory_agents", phase: "PreToolUse" } })
      expect([begin, tools]).toEqual(snapshot)
      await execute()
      expect(dispatched).toBe(1)
      const again = await f.project(first)
      expect(again).toEqual(first)
      const later = await f.project([begin, tools, exchange("later", "session", "completed")])
      expect(later.map((m) => m.info.id)).toEqual([begin.info.id, "gate", first[2].info.id, "later"])
      expect(later[0].parts[0].text).toBe("Begin.")
    } finally { f.stop() }
  })

  test("post-fallbacks serialize by arrival, wait for projection, and do not duplicate a response", async () => {
    let release!: () => void
    let started!: () => void
    const blocked = new Promise<void>((resolve) => { release = resolve })
    const entered = new Promise<void>((resolve) => { started = resolve })
    const f = await fixture(async (payload) => {
      if (payload.tool_input.guide === "A") { started(); await blocked }
    })
    try {
      const first = f.after("A", "nested-A")
      await entered
      const second = f.after("B", "nested-B")
      // CodeMode nested IDs need not appear as top-level tool call IDs.
      const projection = f.project([user(), exchange("program", "session", "completed")])
      expect(f.calls).toHaveLength(1)
      release()
      await Promise.all([first, second])
      const messages = await projection
      expect(f.calls.map((p) => p.tool_input.guide)).toEqual(["A", "B"])
      expect(messages.slice(2).map((m) => m.parts[0].text?.slice(-1))).toEqual(["A", "B"])
      expect(new Set(messages.map((m) => m.info.id)).size).toBe(4)
      await f.after("A", "nested-A", "session", true)
      expect(await f.project(messages)).toEqual(messages)
    } finally { release(); f.stop() }
  })

  test("simultaneous pre-calls stay latched until projection and then gate the next unseen scope", async () => {
    const f = await fixture()
    try {
      let dispatched = 0
      const execute = async (guide: string) => {
        await f.before(guide, guide)
        dispatched++
      }
      const results = await Promise.allSettled([execute("A"), execute("B")])
      expect(results.map((result) => result.status)).toEqual(["rejected", "rejected"])
      expect(dispatched).toBe(0)
      expect(f.calls.map((call) => call.tool_input.guide)).toEqual(["A"])
      const batch = exchange("batch")
      batch.parts.push({ ...batch.parts[0], callID: "second-call" })
      const snapshot = structuredClone(batch)
      const first = await f.project([user(), batch])
      expect(batch).toEqual(snapshot)
      expect(first[1]).toEqual(batch)
      await expect(execute("B")).rejects.toThrow("tool was not executed")
      const next = await f.project([user(), batch, exchange("B-gate")])
      expect(next[2]).toEqual(first[2])
      expect(next[4].parts[0].text).toContain("B")
      await execute("B")
      expect(dispatched).toBe(1)
    } finally { f.stop() }
  })

  test("cumulative revisions and multi-scope bodies retain original positions and path identities", async () => {
    const f = await fixture()
    try {
      const a = '<AGENTS_MD path="/A/AGENTS.md">\nsame\n</AGENTS_MD>'
      const b = '<AGENTS_MD path="/B/AGENTS.md">\nsame\n</AGENTS_MD>'
      const revised = '<AGENTS_MD path="/A/AGENTS.md">\nrevised\n</AGENTS_MD>'
      const combined = a + "\n\n" + b
      await expect(f.before(combined)).rejects.toThrow("tool was not executed")
      const first = await f.project([user(), exchange("ab")])
      expect(first).toHaveLength(3)
      expect(first[2].parts[0].text).toContain(combined)
      await expect(f.before(revised)).rejects.toThrow("tool was not executed")
      const next = await f.project([user(), exchange("ab"), exchange("revision")])
      expect(next.map((m) => m.info.id).slice(0, 3)).toEqual(first.map((m) => m.info.id))
      expect(next[4].parts[0].text).toContain(revised)
      await expect(f.before(combined)).resolves.toBeUndefined()
      expect(await f.project(next)).toHaveLength(5)
    } finally { f.stop() }
  })

  test("pending results or lost anchors fail closed without releasing the gate or relocating a guide", async () => {
    const f = await fixture()
    try {
      await expect(f.before("A")).rejects.toThrow("tool was not executed")
      await expect(f.project([user(), exchange("gate", "session", "running")])).rejects.toThrow("completed tool results")
      await expect(f.before("A")).rejects.toThrow("tool was not executed")
      const first = await f.project([user(), exchange("gate")])
      await expect(f.before("B")).rejects.toThrow("tool was not executed")
      await expect(f.project([user(), exchange("different-history")])).rejects.toThrow("anchor disappeared")
      await expect(f.before("B")).rejects.toThrow("tool was not executed")
      const next = await f.project([user(), exchange("gate"), exchange("second-gate")])
      expect(next[2]).toEqual(first[2])
      expect(next[4].parts[0].text).toContain("B")
    } finally { f.stop() }
  })

  test("late fallback is anchored at first visibility and copied text is never treated as managed", async () => {
    const f = await fixture()
    try {
      await f.project([user(), exchange("early", "session", "completed")])
      await f.after("late guide", "old-call")
      await expect(f.before("")).rejects.toThrow("tool was not executed")
      const copy = user()
      copy.info.id = "actual-user-copy"
      copy.parts[0].text = "late guide"
      const first = await f.project([user(), exchange("early", "session", "completed"), copy])
      expect(first[2]).toEqual(copy)
      expect(first[3].parts[0].text).toContain("late guide")
      const next = await f.project([...first, exchange("later")])
      expect(next[3]).toEqual(first[3])
      expect(next.at(-1)?.info.id).toBe("later")
      await expect(f.before("")).resolves.toBeUndefined()
    } finally { f.stop() }
  })

  test("sessions are isolated and blank context does not add a synthetic request", async () => {
    const f = await fixture()
    try {
      await expect(f.before("")).resolves.toBeUndefined()
      expect(await f.project([user()])).toEqual([user()])
      await expect(f.before("A")).rejects.toThrow("tool was not executed")
      expect(await f.project([user("other")])).toEqual([user("other")])
      await expect(f.before("A")).rejects.toThrow("tool was not executed")
      const messages = await f.project([user(), exchange("gate")])
      expect(messages[2].info.sessionID).toBe("session")
    } finally { f.stop() }
  })
})

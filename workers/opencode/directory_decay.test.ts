import { describe, expect, test } from "bun:test"

import { acknowledgedStream } from "../../third_party/opencode/packages/opencode/src/session/llm/managed-inference.ts"
import { DIRECTORY_DECAY_FACTORY } from "./directory_decay.ts"

const BASE = "826d9ad46a22bef0294998e08daa3c4904fea28f"
const GUIDE = { path: "/work/a/AGENTS.md", digest: "digest-a", content: "private guide body" }
const OTHER = { path: "/work/b/AGENTS.md", digest: "digest-b", content: "other guide body" }

function user(id = "begin", text = "Begin.") {
  return {
    info: {
      id, sessionID: "session", role: "user", time: { created: 1 },
      agent: "build", model: { providerID: "fixture", modelID: "fixture" },
    },
    parts: [{ type: "text", text }],
  }
}

function assistant(id: string, output = "ordinary tool output") {
  return {
    info: { id, sessionID: "session", role: "assistant" },
    parts: [{ type: "tool", state: { status: "completed", output } }],
  }
}

async function fixture(steps: string) {
  const audit: Array<Record<string, unknown>> = []
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      if (request.headers.get("authorization") !== "Bearer fixture-token") {
        return new Response("unauthorized", { status: 401 })
      }
      const payload = await request.json() as {
        hook_event_name: string
        record?: Record<string, unknown>
        tool_input?: { guide?: typeof GUIDE }
      }
      if (payload.hook_event_name === "ManagedContextAudit") {
        audit.push(payload.record ?? {})
        return Response.json({ ok: true })
      }
      return Response.json({
        resolution: {
          schema: 1,
          guides: payload.tool_input?.guide ? [payload.tool_input.guide] : [],
          observations: [{ status: payload.tool_input?.guide ? "loaded" : "unknown" }],
        },
      })
    },
  })
  const make = new Function(DIRECTORY_DECAY_FACTORY + "\nreturn directoryDecay")() as (
    input: unknown, steps: string, endpoint: string, token: string,
  ) => Record<string, (input: unknown, output?: unknown) => Promise<void>>
  const hooks = make(
    { metalanguage: { inference: 1, base: BASE } },
    steps,
    "http://127.0.0.1:" + server.port + "/directory-agents",
    "fixture-token",
  )
  const project = async (id: string, messages: unknown[]) => {
    const output = { messages }
    await hooks["experimental.chat.messages.transform"]!({ sessionID: "session", inferenceID: id, lifecycle: 1 }, output)
    return output.messages as Array<{ info: { id: string }; parts: Array<{ text?: string }> }>
  }
  const inference = (id: string, phase: "prepare" | "acknowledged") =>
    hooks["experimental.chat.inference"]!(
      { sessionID: "session", inferenceID: id, phase, responseID: phase === "acknowledged" ? "resp-" + id : undefined },
      { required: false },
    )
  const before = (id: string, callID: string, guide?: typeof GUIDE) =>
    hooks["tool.execute.before"]!(
      { sessionID: "session", inferenceID: id, programID: "program-" + id, callID, tool: "bash" },
      { args: { guide } },
    )
  const after = (id: string, callID: string, guide?: typeof GUIDE) =>
    hooks["tool.execute.after"]!(
      { sessionID: "session", inferenceID: id, programID: "program-" + id, callID, tool: "bash", args: { guide } },
    )
  return { audit, project, inference, before, after, stop: () => server.stop(true) }
}

describe("OpenCode managed K inference decay", () => {
  test("K=1 renews at the original position, expires owned IDs, and gates identical reentry", async () => {
    const f = await fixture("1")
    try {
      const beginning = user()
      await f.project("one", [beginning])
      await f.inference("one", "acknowledged")
      await expect(f.before("one", "call-a", GUIDE)).rejects.toThrow("tool was not executed")

      const gate = assistant("gate")
      const second = await f.project("two", [beginning, gate])
      const originalID = second[2]!.info.id
      expect(second.map((message) => message.info.id)).toEqual(["begin", "gate", originalID])
      expect(second[2]!.parts[0]!.text).toContain('<AGENTS_MD path="/work/a/AGENTS.md">\nprivate guide body\n</AGENTS_MD>')
      await f.inference("two", "acknowledged")
      await f.before("two", "renew-a", GUIDE)

      const completed = assistant("completed")
      const third = await f.project("three", [beginning, gate, completed])
      expect(third.map((message) => message.info.id)).toEqual(["begin", "gate", originalID, "completed"])
      await f.inference("three", "acknowledged")

      const copy = user("copy", "private guide body copied by a user")
      const fourth = await f.project("four", [beginning, gate, completed, copy])
      expect(fourth.map((message) => message.info.id)).toEqual(["begin", "gate", "completed", "copy"])
      expect(fourth[2]).toEqual(completed)
      expect(fourth[3]).toEqual(copy)
      await f.inference("four", "acknowledged")
      await expect(f.before("four", "reenter-a", GUIDE)).rejects.toThrow("tool was not executed")
      const fifth = await f.project("five", [beginning, gate, completed, copy, assistant("reentry")])
      expect(fifth.at(-1)!.info.id).not.toBe(originalID)
      expect(fifth.at(-1)!.parts[0]!.text).toContain("private guide body")
      expect(JSON.stringify(f.audit)).not.toContain("private guide body")
      expect(f.audit.filter((record) => record.event === "acknowledged")).toHaveLength(4)
    } finally {
      f.stop()
    }
  })

  test("one compound program accumulates simultaneous scopes and older cells cannot reopen", async () => {
    const f = await fixture("2")
    try {
      const beginning = user()
      await f.project("one", [beginning])
      await f.inference("one", "acknowledged")
      const results = await Promise.allSettled([
        f.before("one", "program/1", GUIDE),
        f.before("one", "program/2", OTHER),
      ])
      expect(results.map((result) => result.status)).toEqual(["rejected", "rejected"])
      const second = await f.project("two", [beginning, assistant("program")])
      expect(second.map((message) => message.info.id)).toHaveLength(4)
      expect(second[2]!.parts[0]!.text).toContain("private guide body")
      expect(second[3]!.parts[0]!.text).toContain("other guide body")
      await f.inference("two", "acknowledged")
      const revised = { ...GUIDE, digest: "digest-a2", content: "revised guide body" }
      await expect(f.before("two", "program/revision", revised)).rejects.toThrow("tool was not executed")
      const third = await f.project("three", [beginning, assistant("program"), assistant("revision")])
      expect(third.map((message) => message.info.id)).not.toContain(second[2]!.info.id)
      expect(third[2]!.info.id).toBe(second[3]!.info.id)
      expect(third.at(-1)!.parts[0]!.text).toContain("revised guide body")
      await f.inference("three", "acknowledged")
      await expect(f.before("one", "program/late", GUIDE)).rejects.toThrow("tool was not executed")
      await f.after("one", "program/late", GUIDE)
      expect(f.audit.some((record) => record.event === "stale_access")).toBe(true)
      await expect(f.inference("three", "prepare")).rejects.toThrow("cannot be resubmitted")
    } finally {
      f.stop()
    }
  })

  test("a completed parallel call may publish post-tool context after its sibling defers", async () => {
    const f = await fixture("2")
    try {
      const beginning = user()
      await f.project("one", [beginning])
      await f.inference("one", "acknowledged")
      await f.before("one", "program/allowed")
      await expect(f.before("one", "program/deferred", GUIDE)).rejects.toThrow("tool was not executed")
      await f.after("one", "program/allowed", OTHER)
      const next = await f.project("two", [beginning, assistant("program")])
      expect(next[2]!.parts[0]!.text).toContain("private guide body")
      expect(next[3]!.parts[0]!.text).toContain("other guide body")
      expect(f.audit.filter((record) => record.event === "access_committed" && record.post === true)).toHaveLength(1)
    } finally {
      f.stop()
    }
  })

  test("post-tool observation requires the exact admitted program and call", async () => {
    const f = await fixture("2")
    try {
      await f.project("one", [user()])
      await f.inference("one", "acknowledged")
      await expect(f.after("one", "never-admitted", GUIDE)).rejects.toThrow("matching admitted call")
      expect(f.audit.some((record) => record.event === "access_committed")).toBe(false)
    } finally {
      f.stop()
    }
  })

  test("provider metadata must be acknowledged before model output and cannot change IDs", async () => {
    const seen: string[] = []
    const source = new ReadableStream<{ type: string; id?: string }>({
      start(controller) {
        controller.enqueue({ type: "stream-start" })
        controller.enqueue({ type: "response-metadata", id: "resp-1" })
        controller.enqueue({ type: "tool-call" })
        controller.close()
      },
    })
    const reader = acknowledgedStream(source, async (id) => { seen.push(id) }).getReader()
    const parts: string[] = []
    for (;;) {
      const next = await reader.read()
      if (next.done) break
      parts.push(next.value.type)
      if (next.value.type === "tool-call") expect(seen).toEqual(["resp-1"])
    }
    expect(parts).toEqual(["stream-start", "response-metadata", "tool-call"])

    const missing = new ReadableStream<{ type: string; id?: string }>({
      start(controller) { controller.enqueue({ type: "tool-call" }); controller.close() },
    })
    await expect(acknowledgedStream(missing, async () => {}).getReader().read()).rejects.toThrow("before managed inference")

    const changed = new ReadableStream<{ type: string; id?: string }>({
      start(controller) {
        controller.enqueue({ type: "response-metadata", id: "resp-1" })
        controller.enqueue({ type: "response-metadata", id: "resp-2" })
        controller.close()
      },
    })
    const changedReader = acknowledgedStream(changed, async () => {}).getReader()
    await changedReader.read()
    await expect(changedReader.read()).rejects.toThrow("Multiple provider responses")

    const empty = new ReadableStream<{ type: string }>({
      start(controller) { controller.close() },
    })
    await expect(acknowledgedStream(empty, async () => {}).getReader().read()).rejects.toThrow("without managed inference")
  })

  test("unacknowledged transport retries keep a single pending snapshot and age zero steps", async () => {
    const f = await fixture("2")
    try {
      const beginning = user()
      const first = await f.project("one", [beginning])
      await f.inference("one", "prepare")
      await f.inference("one", "prepare")
      expect(await f.project("one", [beginning])).toEqual(first)
      expect(f.audit.filter((record) => record.event === "acknowledged")).toHaveLength(0)
      await f.inference("one", "acknowledged")
      expect(f.audit.filter((record) => record.event === "acknowledged")).toHaveLength(1)
    } finally {
      f.stop()
    }
  })
})

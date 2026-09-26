import { isRecord } from "./protocol.ts"

export const TOOL_SOURCE = `export default {
  description: "Spawn at most one child rollout from a prepared workspace. Validation failures are retryable and the parent rollout continues after the tool result.",
  args: {
    prompt: { type: "string", minLength: 1, description: "Task prompt for the child rollout." },
    workspace_dir: { type: "string", minLength: 1, description: "Prepared workspace directory containing a non-empty AGENTS.md." },
  },
  async execute(args, context) {
    const endpoint = process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT
    const token = process.env.METALANGUAGE_SPAWN_CHILD_TOKEN
    const failure = (error_code, error) => JSON.stringify({
      success: false,
      child_spawned: false,
      parent_continues: true,
      retryable: true,
      error_code,
      error,
    })
    if (!endpoint || !token) return failure("spawn_child_bridge_unavailable", "spawn_child bridge is unavailable")
    const payload = JSON.stringify({
      tool: "spawn_child",
      namespace: null,
      call_id: context.callID ?? null,
      arguments: args,
    })
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          authorization: \`Bearer \${token}\`,
          "content-type": "application/json",
        },
        body: payload,
        signal: context.abort,
      })
      const body = await response.text()
      if (!response.ok) return failure("spawn_child_bridge_failed", "spawn_child bridge request failed")
      let parsed
      try {
        parsed = JSON.parse(body)
      } catch {
        return failure("spawn_child_bridge_malformed_response", "spawn_child bridge returned a malformed response")
      }
      if (!parsed || typeof parsed !== "object" || typeof parsed.success !== "boolean") {
        return failure("spawn_child_bridge_malformed_response", "spawn_child bridge returned a malformed response")
      }
      return JSON.stringify(parsed)
    } catch (error) {
      if (context.abort?.aborted) throw error
      return failure("spawn_child_bridge_failed", "spawn_child bridge request failed")
    }
  },
}
`

export const SYSTEM_PLUGIN_SOURCE = `export default async function metalanguageSystemPlugin() {
  const managedContexts = new Map()
  const deferredSessions = new Set()
  const gateQueues = new Map()
  // Serialize both pre-gates and post-fallbacks in callback arrival order.
  const enqueue = async (sessionID, action) => {
    const prior = gateQueues.get(sessionID) ?? Promise.resolve()
    const gate = prior.catch(() => {}).then(action)
    gateQueues.set(sessionID, gate)
    try {
      return await gate
    } finally {
      if (gateQueues.get(sessionID) === gate) gateQueues.delete(sessionID)
    }
  }
  const activate = async (sessionID, payload) => {
    const endpoint = process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT
    const token = process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN
    try {
      if (!endpoint || !token) return { additional_context: "", defer: false }
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          authorization: \`Bearer \${token}\`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ ...payload, session_id: sessionID }),
      })
      if (!response.ok) return { additional_context: "", defer: false }
      const parsed = await response.json()
      const context = parsed?.additional_context
      if (typeof context === "string" && context.trim()) {
        const additions = managedContexts.get(sessionID) ?? []
        if (!additions.some((entry) => entry.context === context)) {
          additions.push({
            id: "msg_metalanguage_" + crypto.randomUUID(),
            context,
            callID: payload.tool_use_id,
            phase: payload.hook_event_name,
            created: Date.now(),
          })
          // Even a fallback must become visible before admitting another call.
          deferredSessions.add(sessionID)
        }
        managedContexts.set(sessionID, additions)
      }
      return parsed
    } catch {
      return { additional_context: "", defer: false }
    }
  }
  return {
    "experimental.chat.system.transform": async (input, output) => {
      if (!input.sessionID) return
      const exact = process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS
      if (exact !== undefined) output.system.splice(0, output.system.length, exact)
    },
    "experimental.chat.messages.transform": async (_input, output) => {
      const sessions = new Set(output.messages.map((message) => message.info.sessionID))
      if (!sessions.size) return
      if (sessions.size !== 1) throw new Error("Managed context projection requires one session.")
      const sessionID = [...sessions][0]
      // Drain callbacks already admitted, including ones queued while waiting.
      while (gateQueues.has(sessionID)) await gateQueues.get(sessionID).catch(() => {})
      const additions = managedContexts.get(sessionID) ?? []
      const ownedIDs = new Set(additions.map((entry) => entry.id))
      // A retry may reuse the transformed array. Only remove our owned IDs.
      const messages = output.messages.filter((message) => !ownedIDs.has(message.info.id))
      const positions = new Map(messages.map((message, index) => [message.info.id, index]))
      if (positions.size !== messages.length) throw new Error("Duplicate conversation message identity.")
      const pending = additions.filter((entry) => !entry.message)
      const anchor = messages.at(-1)
      const user = messages.findLast((message) => message.info.role === "user")
      if (pending.length && (!anchor || !user)) {
        throw new Error("Managed context projection has no conversation anchor.")
      }
      // Insert only between whole session messages. The upstream converter
      // expands each assistant message's tool calls AND results together.
      // Nested CodeMode call IDs need not be top-level conversation part IDs.
      if (pending.length && anchor.parts.some((part) =>
        part.type === "tool" && !["completed", "error"].includes(part.state?.status)
      )) throw new Error("Managed context projection requires completed tool results.")
      for (const entry of additions) {
        if (entry.message && !positions.has(entry.anchorID)) {
          throw new Error("Managed context conversation anchor disappeared; refusing to relocate guidance.")
        }
      }
      for (const entry of pending) {
        entry.anchorID = anchor.info.id
        entry.message = {
          info: {
            id: entry.id,
            sessionID,
            role: "user",
            time: { created: entry.created },
            agent: user.info.agent,
            model: { ...user.info.model },
          },
          parts: [{
            id: "prt_" + entry.id,
            sessionID,
            messageID: entry.id,
            type: "text",
            synthetic: true,
            metadata: { metalanguage: { kind: "directory_agents", id: entry.id, callID: entry.callID, phase: entry.phase } },
            text: "[Metalanguage automatic directory context; synthetic user-role message, not a new human request.]\\n\\n" + entry.context,
          }],
        }
      }
      const after = new Map()
      for (const entry of additions) {
        const group = after.get(entry.anchorID) ?? []
        group.push(entry.message)
        after.set(entry.anchorID, group)
      }
      const projected = messages.flatMap((message) => [
        message,
        ...(after.get(message.info.id) ?? []).map((managed) => structuredClone(managed)),
      ])
      output.messages.splice(0, output.messages.length, ...projected)
      // System transforms/retries cannot release the gate before projection.
      deferredSessions.delete(sessionID)
    },
    "tool.execute.before": async (input, output) => {
      if (!input.sessionID || !input.callID) return
      await enqueue(input.sessionID, async () => {
        if (deferredSessions.has(input.sessionID)) {
          throw new Error("Local context activated; tool was not executed.")
        }
        const result = await activate(input.sessionID, {
          hook_event_name: "PreToolUse",
          tool_name: input.tool,
          tool_input: output.args,
          tool_use_id: input.callID,
        })
        if (result?.defer === true) deferredSessions.add(input.sessionID)
        if (!deferredSessions.has(input.sessionID)) return
        throw new Error(
          typeof result.neutral_result === "string"
            ? result.neutral_result
            : "Local context activated; tool was not executed.",
        )
      })
    },
    "tool.execute.after": async (input, _output) => {
      if (!input.sessionID || !input.callID) return
      await enqueue(input.sessionID, () => activate(input.sessionID, {
        hook_event_name: "PostToolUse",
        tool_name: input.tool,
        tool_input: input.args,
        tool_use_id: input.callID,
      }))
    },
    "shell.env": async (_input, output) => {
      const configured = process.env.METALANGUAGE_OPENCODE_PROVIDER_ENV_NAMES ?? "[]"
      let names = []
      try { names = JSON.parse(configured) } catch {}
      for (const name of [
        ...names,
        "OPENCODE_AUTH_CONTENT",
        "OPENCODE_SERVER_PASSWORD",
        "METALANGUAGE_SPAWN_CHILD_ENDPOINT",
        "METALANGUAGE_SPAWN_CHILD_TOKEN",
        "METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT",
        "METALANGUAGE_DIRECTORY_AGENTS_TOKEN",
      ]) {
        if (typeof name === "string" && name) delete output.env[name]
      }
    },
  }
}
`

export function systemPluginSource(
  directoryAgents?: { endpoint: string; token: string },
): string {
  if (!directoryAgents) return SYSTEM_PLUGIN_SOURCE
  return SYSTEM_PLUGIN_SOURCE
    .replace(
      "process.env.METALANGUAGE_DIRECTORY_AGENTS_ENDPOINT",
      JSON.stringify(directoryAgents.endpoint),
    )
    .replace(
      "process.env.METALANGUAGE_DIRECTORY_AGENTS_TOKEN",
      JSON.stringify(directoryAgents.token),
    )
}

function failure(code: string, message: string): Record<string, unknown> {
  return {
    success: false,
    child_spawned: false,
    parent_continues: true,
    retryable: true,
    error_code: code,
    error: message,
  }
}

export async function runHandler(command: string[], payload: unknown, timeoutMs = 15_000): Promise<unknown> {
  const tool = isRecord(payload) ? payload.tool : undefined
  if (tool !== "spawn_child") {
    return failure("unsupported_dynamic_tool", "dynamic tool bridge supports only spawn_child")
  }
  if (!command.length) {
    return failure("spawn_child_handler_unavailable", "spawn_child handler command is empty")
  }
  let child: Bun.PipedSubprocess
  try {
    child = Bun.spawn(command, { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
  } catch {
    return failure("spawn_child_handler_crashed", "spawn_child handler could not start")
  }
  const terminate = () => child.kill("SIGTERM")
  process.once("SIGTERM", terminate)
  process.once("SIGINT", terminate)
  try {
    child.stdin.write(`${JSON.stringify(payload)}\n`)
    child.stdin.end()
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("timeout")), Math.max(1, timeoutMs))
    })
    let stdout: string
    let code: number
    try {
      ;[stdout, , code] = await Promise.race([
        Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ]),
        timeout,
      ])
    } catch {
      child.kill("SIGKILL")
      await child.exited
      return failure("spawn_child_handler_timeout", "spawn_child handler timed out")
    } finally {
      if (timer) clearTimeout(timer)
    }
    if (code !== 0) {
      return failure("spawn_child_handler_crashed", "spawn_child handler crashed")
    }
    if (!stdout.trim()) {
      return failure("spawn_child_handler_malformed_response", "spawn_child handler returned an empty response")
    }
    try {
      const parsed = JSON.parse(stdout.trim())
      if (!isRecord(parsed) || typeof parsed.success !== "boolean") {
        return failure("spawn_child_handler_malformed_response", "spawn_child handler returned a malformed response")
      }
      return parsed
    } catch {
      return failure("spawn_child_handler_malformed_response", "spawn_child handler returned a malformed response")
    }
  } finally {
    process.off("SIGTERM", terminate)
    process.off("SIGINT", terminate)
  }
}

export async function runDirectoryAgentsHandler(
  command: string[],
  payload: unknown,
  timeoutMs = 15_000,
): Promise<{ additional_context: string; defer: boolean; neutral_result?: string }> {
  const empty = { additional_context: "", defer: false }
  if (
    !command.length ||
    !isRecord(payload) ||
    !["PreToolUse", "PostToolUse"].includes(String(payload.hook_event_name))
  ) return empty
  let child: Bun.PipedSubprocess
  try {
    child = Bun.spawn(command, { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
  } catch {
    return empty
  }
  const terminate = () => child.kill("SIGTERM")
  process.once("SIGTERM", terminate)
  process.once("SIGINT", terminate)
  try {
    child.stdin.write(`${JSON.stringify(payload)}\n`)
    child.stdin.end()
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("timeout")), Math.max(1, timeoutMs))
    })
    let stdout: string
    let code: number
    try {
      ;[stdout, , code] = await Promise.race([
        Promise.all([
          new Response(child.stdout).text(),
          new Response(child.stderr).text(),
          child.exited,
        ]),
        timeout,
      ])
    } catch {
      child.kill("SIGKILL")
      await child.exited
      return empty
    } finally {
      if (timer) clearTimeout(timer)
    }
    if (code !== 0 || !stdout.trim()) return empty
    try {
      const parsed = JSON.parse(stdout.trim())
      const hookOutput = isRecord(parsed) ? parsed.hookSpecificOutput : undefined
      if (
        !isRecord(hookOutput) ||
        hookOutput.hookEventName !== payload.hook_event_name ||
        typeof hookOutput.additionalContext !== "string"
      ) {
        return empty
      }
      const defer =
        payload.hook_event_name === "PreToolUse" &&
        hookOutput.permissionDecision === "deny"
      return {
        additional_context: hookOutput.additionalContext,
        defer,
        ...(defer && typeof hookOutput.permissionDecisionReason === "string"
          ? { neutral_result: hookOutput.permissionDecisionReason }
          : {}),
      }
    } catch {
      return empty
    }
  } finally {
    process.off("SIGTERM", terminate)
    process.off("SIGINT", terminate)
  }
}

export async function runSpawnBridgeFromStdio(): Promise<void> {
  const rawCommand = process.env.METALANGUAGE_SPAWN_CHILD_HANDLER_COMMAND
  if (!rawCommand) throw new Error("METALANGUAGE_SPAWN_CHILD_HANDLER_COMMAND is not configured")
  const command = JSON.parse(rawCommand)
  if (!Array.isArray(command) || !command.every((item) => typeof item === "string")) {
    throw new Error("spawn_child handler command is invalid")
  }
  const payload = JSON.parse(await Bun.stdin.text())
  const result = await runHandler(command, payload)
  process.stdout.write(JSON.stringify(result))
}

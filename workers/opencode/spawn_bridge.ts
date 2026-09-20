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
        if (!additions.includes(context)) additions.push(context)
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
      deferredSessions.delete(input.sessionID)
      const additions = managedContexts.get(input.sessionID)
      if (additions?.length) output.system.push(additions.join("\\n\\n"))
    },
    "tool.execute.before": async (input, output) => {
      if (!input.sessionID || !input.callID) return
      const prior = gateQueues.get(input.sessionID) ?? Promise.resolve()
      const gate = prior.catch(() => {}).then(async () => {
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
      gateQueues.set(input.sessionID, gate)
      try {
        await gate
      } finally {
        if (gateQueues.get(input.sessionID) === gate) gateQueues.delete(input.sessionID)
      }
    },
    "tool.execute.after": async (input, _output) => {
      if (!input.sessionID || !input.callID) return
      await activate(input.sessionID, {
        hook_event_name: "PostToolUse",
        tool_name: input.tool,
        tool_input: input.args,
        tool_use_id: input.callID,
      })
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

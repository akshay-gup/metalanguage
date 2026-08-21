import { isRecord } from "./protocol.ts"

export const TOOL_SOURCE = `export default {
  description: "Spawn at most one child rollout from a prepared workspace. Validation failures are retryable and the parent rollout continues after the tool result.",
  args: {
    prompt: { type: "string", minLength: 1, description: "Task prompt for the child rollout." },
    workspace_dir: { type: "string", minLength: 1, description: "Prepared workspace directory containing a non-empty README.md." },
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
  return {
    "experimental.chat.system.transform": async (input, output) => {
      if (!input.sessionID) return
      const exact = process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS
      if (exact === undefined) return
      output.system.splice(0, output.system.length, exact)
    },
    "shell.env": async (_input, output) => {
      const configured = process.env.METALANGUAGE_OPENCODE_PROVIDER_ENV_NAMES ?? "[]"
      let names = []
      try { names = JSON.parse(configured) } catch {}
      for (const name of [
        ...names,
        "OPENCODE_AUTH_CONTENT",
        "OPENCODE_SERVER_PASSWORD",
        "METALANGUAGE_SPAWN_CHILD_TOKEN",
      ]) {
        if (typeof name === "string" && name) output.env[name] = ""
      }
    },
  }
}
`

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
  if (!command.length) return failure("spawn_child_handler_unavailable", "spawn_child handler command is empty")
  if (!isRecord(payload) || payload.tool !== "spawn_child") {
    return failure("unsupported_dynamic_tool", "spawn_child bridge only supports spawn_child")
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
    if (code !== 0) return failure("spawn_child_handler_crashed", "spawn_child handler crashed")
    if (!stdout.trim()) return failure("spawn_child_handler_malformed_response", "spawn_child handler returned an empty response")
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

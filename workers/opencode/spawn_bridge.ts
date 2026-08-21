import { isRecord } from "./protocol.ts"

export const TOOL_SOURCE = `export default {
  description: "Spawn at most one child rollout from a prepared workspace. Validation failures are retryable and the parent rollout continues after the tool result.",
  args: {
    prompt: { type: "string", minLength: 1, description: "Task prompt for the child rollout." },
    workspace_dir: { type: "string", minLength: 1, description: "Prepared workspace directory containing a non-empty README.md." },
  },
  async execute(args, context) {
    const bun = process.env.METALANGUAGE_OPENCODE_BUN_BIN
    const worker = process.env.METALANGUAGE_OPENCODE_WORKER_SCRIPT
    if (!bun || !worker) throw new Error("Metalanguage spawn_child bridge is not configured")
    const payload = JSON.stringify({
      tool: "spawn_child",
      namespace: null,
      call_id: context.callID ?? null,
      arguments: args,
    })
    const child = Bun.spawn([bun, worker, "spawn-child-bridge"], {
      env: process.env,
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
    })
    const abort = () => child.kill()
    context.abort.addEventListener("abort", abort, { once: true })
    try {
      child.stdin.write(payload)
      child.stdin.end()
      const [stdout, stderr, code] = await Promise.all([
        new Response(child.stdout).text(),
        new Response(child.stderr).text(),
        child.exited,
      ])
      if (code !== 0) throw new Error(\`spawn_child bridge exited \${code}: \${stderr.trim()}\`)
      return JSON.stringify(JSON.parse(stdout))
    } finally {
      context.abort.removeEventListener("abort", abort)
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

export async function runHandler(command: string[], payload: unknown): Promise<unknown> {
  if (!command.length) throw new Error("spawn_child handler command is empty")
  if (!isRecord(payload) || payload.tool !== "spawn_child") {
    return failure("unsupported_dynamic_tool", "spawn_child bridge only supports spawn_child")
  }
  const child = Bun.spawn(command, { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
  const terminate = () => child.kill("SIGTERM")
  process.once("SIGTERM", terminate)
  process.once("SIGINT", terminate)
  try {
    child.stdin.write(`${JSON.stringify(payload)}\n`)
    child.stdin.end()
    const [stdout, stderr, code] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ])
    if (code !== 0) throw new Error(`spawn_child handler exited ${code}: ${stderr.trim()}`)
    if (!stdout.trim()) throw new Error("spawn_child handler returned empty stdout")
    try {
      return JSON.parse(stdout.trim())
    } catch (error) {
      throw new Error("parse spawn_child handler response", { cause: error })
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
  let result: unknown
  try {
    result = await runHandler(command, payload)
  } catch (error) {
    result = failure("spawn_child_handler_failed", error instanceof Error ? error.message : String(error))
  }
  process.stdout.write(JSON.stringify(result))
}

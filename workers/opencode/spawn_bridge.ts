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

function peerMessageToolSource(tool: string, description: string, args: string): string {
  return `export default {
  description: ${JSON.stringify(description)},
  args: ${args},
  async execute(args, context) {
    const endpoint = process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT
    const token = process.env.METALANGUAGE_SPAWN_CHILD_TOKEN
    const failure = (error_code, error) => JSON.stringify({
      success: false,
      tool: ${JSON.stringify(tool)},
      retryable: true,
      error_code,
      error,
    })
    if (!endpoint || !token) return failure("peer_communication_bridge_unavailable", "peer communication bridge is unavailable")
    const payload = JSON.stringify({
      tool: ${JSON.stringify(tool)},
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
      if (!response.ok) return failure("peer_communication_bridge_failed", "peer communication bridge request failed")
      let parsed
      try {
        parsed = JSON.parse(body)
      } catch {
        return failure("peer_communication_bridge_malformed_response", "peer communication bridge returned a malformed response")
      }
      if (!parsed || typeof parsed !== "object" || typeof parsed.success !== "boolean") {
        return failure("peer_communication_bridge_malformed_response", "peer communication bridge returned a malformed response")
      }
      return JSON.stringify(parsed)
    } catch (error) {
      if (context.abort?.aborted) throw error
      return failure("peer_communication_bridge_failed", "peer communication bridge request failed")
    }
  },
}
`
}

export const SEND_MESSAGE_TOOL_SOURCE = peerMessageToolSource(
  "send_message",
  "Send a bounded non-empty UTF-8 direct message to a named peer in the current batch. The receiver must exactly match a peer name in runtime.md. Delivery is automatic at a subsequent supported inference boundary.",
  `{ message: { type: "string", minLength: 1, description: "A bounded non-empty UTF-8 message (maximum 2048 bytes)." }, receiver: { type: "string", minLength: 1, description: "The exact peer name listed in runtime.md." } }`,
)

export const SYSTEM_PLUGIN_SOURCE = `export default async function metalanguageSystemPlugin() {
  const pendingAcknowledgements = new Map()
  const peerRequest = async (tool, args) => {
    const endpoint = process.env.METALANGUAGE_SPAWN_CHILD_ENDPOINT
    const token = process.env.METALANGUAGE_SPAWN_CHILD_TOKEN
    if (!endpoint || !token) return undefined
    let response
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          authorization: \`Bearer \${token}\`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ tool, namespace: null, arguments: args }),
      })
    } catch {
      throw new Error("peer delivery supervisor transport failed")
    }
    if (!response.ok) throw new Error("peer delivery supervisor rejected transport")
    let result
    try { result = await response.json() } catch {
      throw new Error("peer delivery supervisor returned malformed JSON")
    }
    if (!result || typeof result !== "object" || result.success !== true) {
      throw new Error("peer delivery supervisor rejected operation")
    }
    return result
  }
  const syntheticID = (prefix) => {
    const suffix = crypto.getRandomValues(new Uint8Array(12))
    return prefix + "_peer_" + [...suffix].map((byte) => byte.toString(16).padStart(2, "0")).join("")
  }
  return {
    "tool.definition": async (input, output) => {
      if (input.toolID === "send_message") output.jsonSchema = {
        type: "object",
        properties: {
          message: { type: "string", minLength: 1, description: "A bounded non-empty UTF-8 message (maximum 2048 bytes)." },
          receiver: { type: "string", minLength: 1, description: "The exact peer name listed in runtime.md." },
        },
        required: ["message", "receiver"],
        additionalProperties: false,
      }
    },
    "experimental.chat.system.transform": async (input, output) => {
      if (!input.sessionID) return
      const exact = process.env.METALANGUAGE_OPENCODE_SYSTEM_INSTRUCTIONS
      if (exact === undefined) return
      output.system.splice(0, output.system.length, exact)
    },
    "experimental.chat.messages.transform": async (_input, output) => {
      if (process.env.METALANGUAGE_PEER_COMMUNICATION_ENABLED !== "1") return
      const prepared = await peerRequest("_peer_delivery_prepare", {})
      if (!prepared || prepared.pending !== true) return
      if (
        typeof prepared.delivery_id !== "string" || !prepared.delivery_id ||
        typeof prepared.injection !== "string" || !prepared.injection ||
        new TextEncoder().encode(prepared.injection).byteLength > 8192
      ) throw new Error("peer delivery supervisor returned malformed preparation")
      const lastUser = [...output.messages].reverse().find((message) => message?.info?.role === "user")
      if (!lastUser) throw new Error("peer delivery cannot locate active OpenCode user context")
      const messageID = syntheticID("msg")
      const synthetic = {
        info: {
          id: messageID,
          sessionID: lastUser.info.sessionID,
          role: "user",
          time: { created: Date.now() },
          agent: lastUser.info.agent,
          model: lastUser.info.model,
        },
        parts: [{
          id: syntheticID("prt"),
          sessionID: lastUser.info.sessionID,
          messageID,
          type: "text",
          text: prepared.injection,
          synthetic: true,
        }],
      }
      output.messages.push(synthetic)
      pendingAcknowledgements.set(lastUser.info.sessionID, prepared.delivery_id)
    },
    "chat.params": async (input, _output) => {
      const deliveryID = pendingAcknowledgements.get(input.sessionID)
      if (!deliveryID) return
      try {
        const acknowledged = await peerRequest("_peer_delivery_ack", { delivery_id: deliveryID })
        if (!acknowledged || acknowledged.committed !== true) {
          throw new Error("peer delivery acknowledgement was not committed")
        }
      } catch {
        throw new Error("peer delivery acknowledgement failed")
      }
      pendingAcknowledgements.delete(input.sessionID)
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
        "METALANGUAGE_PEER_COMMUNICATION_ENABLED",
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

function peerFailure(tool: string, code: string, message: string): Record<string, unknown> {
  return { success: false, tool, retryable: true, error_code: code, error: message }
}

export async function runHandler(command: string[], payload: unknown, timeoutMs = 15_000): Promise<unknown> {
  const tool = isRecord(payload) && typeof payload.tool === "string" ? payload.tool : ""
  const peer = [
    "send_message",
    "_peer_delivery_prepare",
    "_peer_delivery_ack",
    "_peer_delivery_claim",
    "_peer_delivery_ack_boundary",
    "_peer_delivery_cycle_started",
  ].includes(tool)
  if (!command.length) {
    return peer
      ? peerFailure(tool, "peer_communication_handler_unavailable", "peer communication handler command is empty")
      : failure("spawn_child_handler_unavailable", "spawn_child handler command is empty")
  }
  if (!isRecord(payload) || !(tool === "spawn_child" || peer)) {
    return failure("unsupported_dynamic_tool", "dynamic tool bridge does not support this tool")
  }
  let child: Bun.PipedSubprocess
  try {
    child = Bun.spawn(command, { stdin: "pipe", stdout: "pipe", stderr: "pipe" })
  } catch {
    return peer
      ? peerFailure(tool, "peer_communication_handler_crashed", "peer communication handler could not start")
      : failure("spawn_child_handler_crashed", "spawn_child handler could not start")
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
      return peer
        ? peerFailure(tool, "peer_communication_handler_timeout", "peer communication handler timed out")
        : failure("spawn_child_handler_timeout", "spawn_child handler timed out")
    } finally {
      if (timer) clearTimeout(timer)
    }
    if (code !== 0) return peer
      ? peerFailure(tool, "peer_communication_handler_crashed", "peer communication handler crashed")
      : failure("spawn_child_handler_crashed", "spawn_child handler crashed")
    if (!stdout.trim()) return peer
      ? peerFailure(tool, "peer_communication_handler_malformed_response", "peer communication handler returned an empty response")
      : failure("spawn_child_handler_malformed_response", "spawn_child handler returned an empty response")
    try {
      const parsed = JSON.parse(stdout.trim())
      if (!isRecord(parsed) || typeof parsed.success !== "boolean") {
        return peer
          ? peerFailure(tool, "peer_communication_handler_malformed_response", "peer communication handler returned a malformed response")
          : failure("spawn_child_handler_malformed_response", "spawn_child handler returned a malformed response")
      }
      return parsed
    } catch {
      return peer
        ? peerFailure(tool, "peer_communication_handler_malformed_response", "peer communication handler returned a malformed response")
        : failure("spawn_child_handler_malformed_response", "spawn_child handler returned a malformed response")
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

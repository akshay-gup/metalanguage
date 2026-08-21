#!/usr/bin/env bun

import { chmod, mkdir, rm } from "node:fs/promises"
import { createServer, type Socket } from "node:net"
import { dirname } from "node:path"

type BridgeRequest = {
  socket_path: string
  command: string[]
  cwd?: string
  env: Record<string, string>
  supervisor_pid: number
}

function parseRequest(): BridgeRequest {
  const value = JSON.parse(process.argv[2] ?? "null")
  if (
    !value ||
    typeof value !== "object" ||
    typeof value.socket_path !== "string" ||
    !value.socket_path.startsWith("/") ||
    !Array.isArray(value.command) ||
    value.command.length === 0 ||
    !value.command.every((item: unknown) => typeof item === "string" && item.length > 0) ||
    (value.cwd !== undefined && typeof value.cwd !== "string") ||
    !value.env ||
    typeof value.env !== "object" ||
    Array.isArray(value.env) ||
    !Object.entries(value.env).every(
      ([key, item]) => typeof key === "string" && typeof item === "string",
    ) ||
    !Number.isInteger(value.supervisor_pid) ||
    value.supervisor_pid <= 1
  ) {
    throw new Error("invalid Metalanguage MCP host bridge request")
  }
  return value as BridgeRequest
}

const request = parseRequest()
await mkdir(dirname(request.socket_path), { recursive: true, mode: 0o700 })
await rm(request.socket_path, { force: true })

const child = Bun.spawn(request.command, {
  cwd: request.cwd,
  env: request.env,
  stdin: "pipe",
  stdout: "pipe",
  stderr: "ignore",
})
let connected = false
let socket: Socket | undefined

const server = createServer((candidate) => {
  if (connected) {
    candidate.destroy()
    return
  }
  connected = true
  socket = candidate
  void (async () => {
    try {
      for await (const chunk of candidate) child.stdin.write(chunk)
    } finally {
      child.stdin.end()
    }
  })()
  const stdout = child.stdout
  if (stdout instanceof ReadableStream) {
    void (async () => {
      const reader = stdout.getReader()
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          if (!candidate.write(value)) await new Promise((resolve) => candidate.once("drain", resolve))
        }
      } finally {
        candidate.end()
      }
    })()
  }
  candidate.once("error", () => child.kill("SIGTERM"))
  candidate.once("close", () => child.kill("SIGTERM"))
})

await new Promise<void>((resolve, reject) => {
  server.once("error", reject)
  server.listen(request.socket_path, () => resolve())
})
await chmod(request.socket_path, 0o600)
process.stdout.write(`${JSON.stringify({ event: "ready", child_pid: child.pid })}\n`)

const terminate = () => {
  socket?.destroy()
  child.kill("SIGTERM")
  server.close()
}
process.once("SIGTERM", terminate)
process.once("SIGINT", terminate)

const supervisor = setInterval(() => {
  try {
    process.kill(request.supervisor_pid, 0)
  } catch {
    terminate()
  }
}, 250)
supervisor.unref()

const code = await child.exited
clearInterval(supervisor)
server.close()
await rm(request.socket_path, { force: true })
process.exit(code)

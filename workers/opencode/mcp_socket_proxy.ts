#!/usr/bin/env bun

import { createConnection } from "node:net"

const socketPath = process.argv[2]
if (!socketPath || !socketPath.startsWith("/")) {
  process.stderr.write("invalid Metalanguage MCP socket proxy request\n")
  process.exit(2)
}

const socket = createConnection(socketPath)
const fail = () => process.exit(1)
socket.once("error", fail)
socket.once("connect", () => {
  socket.off("error", fail)
  process.stdin.pipe(socket)
  socket.pipe(process.stdout)
})
socket.once("close", () => process.exit(0))

const terminate = () => socket.destroy()
process.once("SIGTERM", terminate)
process.once("SIGINT", terminate)

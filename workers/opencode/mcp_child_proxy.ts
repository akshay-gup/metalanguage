#!/usr/bin/env bun

const command = JSON.parse(process.argv[2] ?? "null")
const allowedNames = JSON.parse(process.argv[3] ?? "null")
if (
  !Array.isArray(command) ||
  !command.length ||
  !command.every((item) => typeof item === "string") ||
  !Array.isArray(allowedNames) ||
  !allowedNames.every((item) => typeof item === "string")
) {
  process.stderr.write("invalid Metalanguage MCP proxy request\n")
  process.exit(2)
}

const baseNames = [
  "HOME",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "NO_COLOR",
  "PATH",
  "SSL_CERT_DIR",
  "SSL_CERT_FILE",
  "TERM",
  "TMPDIR",
  "TZ",
  "XDG_CACHE_HOME",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "XDG_STATE_HOME",
]
const env: Record<string, string> = {}
for (const name of [...baseNames, ...allowedNames]) {
  const value = process.env[name]
  if (value !== undefined) env[name] = value
}

const child = Bun.spawn(command, {
  env,
  stdin: "inherit",
  stdout: "inherit",
  stderr: "inherit",
})
const terminate = () => child.kill("SIGTERM")
process.once("SIGTERM", terminate)
process.once("SIGINT", terminate)
const code = await child.exited
process.off("SIGTERM", terminate)
process.off("SIGINT", terminate)
process.exit(code)

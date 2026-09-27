// Plain JavaScript embedded in the isolated server plugin; no runtime imports.
export const DIRECTORY_DECAY_FACTORY = String.raw`
function directoryDecay(input, steps, endpoint, token) {
  const base = "826d9ad46a22bef0294998e08daa3c4904fea28f"
  if (input?.metalanguage?.inference !== 1 || input.metalanguage.base !== base) {
    throw new Error("Directory decay requires the patched Metalanguage inference runtime")
  }
  if (!/^[1-9][0-9]*$/.test(steps)) throw new Error("Directory decay requires explicit positive K")
  const limit = (1n << 64n) - 1n
  const lifetime = BigInt(steps)
  if (lifetime > limit || !endpoint || !token) throw new Error("Invalid directory decay configuration")
  const sessions = new Map()
  const neutral = "Local context activated; tool was not executed."
  const add = (a, b) => {
    const value = a + b
    if (value > limit) throw new Error("Directory decay counter overflow")
    return value
  }
  const request = async (payload) => {
    const response = await fetch(endpoint, {
      method: "POST", headers: { authorization: "Bearer " + token, "content-type": "application/json" },
      body: JSON.stringify(payload),
    })
    if (!response.ok) throw new Error("Directory decay bridge unavailable")
    return response.json()
  }
  const state = (id) => {
    if (!id) throw new Error("Directory decay requires session identity")
    if (!sessions.has(id)) sessions.set(id, {
      submitted: 0n, sequence: 0n, revision: 0n, active: new Map(), owned: new Map(),
      epochs: new Map(), current: undefined, pending: false, queue: Promise.resolve(), failure: undefined,
    })
    return sessions.get(id)
  }
  const serial = (id, action) => {
    const s = state(id)
    const task = s.queue.then(async () => {
      if (s.failure) throw s.failure
      try { return await action(s) } catch (error) { s.failure = error; throw error }
    })
    s.queue = task.catch(() => {})
    return task
  }
  const audit = async (sessionID, record) => {
    const result = await request({ hook_event_name: "ManagedContextAudit", session_id: sessionID, record })
    if (result.ok !== true) throw new Error("Directory decay audit was not committed")
  }
  const observe = (s, epoch, inferenceID) => s.current === inferenceID && epoch?.acknowledged &&
    (epoch.revision === s.revision || epoch.blocked === s.sequence)
  const permitted = (s, epoch) => epoch?.acknowledged && epoch.blocked === undefined && epoch.revision === s.revision
  const escape = (path) => path.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#x27;").replaceAll("\t", "&#9;").replaceAll("\n", "&#10;").replaceAll("\r", "&#13;")
  const access = async (input, args, post) => serial(input.sessionID, async (s) => {
    const epoch = s.epochs.get(input.inferenceID)
    if (!input.programID || !input.callID || !epoch) throw new Error("Tool is missing managed inference/program identity")
    // No late callback may change the immutable request while it is in flight.
    // A denied old program cannot retry after the new request acknowledges.
    if (s.pending) {
      if (!post) epoch.blocked = s.sequence
      await audit(input.sessionID, { event: "pending_access", inference: input.inferenceID, post })
      return false
    }
    if (!observe(s, epoch, input.inferenceID)) {
      await audit(input.sessionID, { event: "stale_access", inference: input.inferenceID, post })
      return false
    }
    if (post) {
      const admitted = epoch.admitted.get(input.callID)
      if (admitted?.programID !== input.programID || admitted.tool !== input.tool) {
        throw new Error("Post-tool context lacks a matching admitted call")
      }
    } else if (epoch.admitted.has(input.callID)) {
      throw new Error("Duplicate tool admission identity")
    }
    const result = await request({ hook_event_name: post ? "PostToolUse" : "PreToolUse",
      session_id: input.sessionID, tool_name: input.tool, tool_input: args, tool_use_id: input.callID })
    const resolved = result.resolution
    if (resolved?.schema !== 1 || !Array.isArray(resolved.guides) || !Array.isArray(resolved.observations)) {
      throw new Error("Malformed directory decay resolution")
    }
    const deadline = add(s.submitted, lifetime)
    const active = new Map(s.active)
    const additions = []
    const renewals = []
    const paths = new Set()
    for (const guide of resolved.guides) {
      if (typeof guide.path !== "string" || !guide.path || typeof guide.digest !== "string" ||
          !guide.digest || typeof guide.content !== "string" || !guide.content.trim() || paths.has(guide.path)) {
        throw new Error("Invalid directory decay guide")
      }
      paths.add(guide.path)
      const previous = active.get(guide.path)
      if (previous?.digest === guide.digest) {
        active.set(guide.path, { ...previous, expires: deadline })
        renewals.push(previous.id)
        continue
      }
      const entry = { id: "msg_metalanguage_" + crypto.randomUUID(), path: guide.path, digest: guide.digest,
        context: '<AGENTS_MD path="' + escape(guide.path) + '">\n' + guide.content.trimEnd() + '\n</AGENTS_MD>',
        expires: deadline, callID: input.callID, phase: post ? "PostToolUse" : "PreToolUse", created: Date.now() }
      active.set(guide.path, entry)
      additions.push(entry)
    }
    const revision = additions.length ? add(s.revision, 1n) : s.revision
    await audit(input.sessionID, { event: "access_prepared", inference: input.inferenceID, program: input.programID,
      step: String(s.submitted), post, revision: String(revision), observations: resolved.observations,
      renewals, additions: additions.map((entry) => ({ id: entry.id, path: entry.path,
        digest: entry.digest, expires: String(entry.expires), callID: entry.callID, phase: entry.phase })) })
    s.active = active
    for (const entry of additions) s.owned.set(entry.id, entry)
    if (additions.length) { s.revision = revision; epoch.blocked = s.sequence }
    if (post) epoch.admitted.delete(input.callID)
    else if (permitted(s, epoch)) epoch.admitted.set(input.callID, { programID: input.programID, tool: input.tool })
    await audit(input.sessionID, { event: "access_committed", inference: input.inferenceID,
      callID: input.callID, post, revision: String(s.revision), admitted: !post && permitted(s, epoch) })
    return permitted(s, epoch)
  })
  return {
    "experimental.chat.messages.transform": async (input, output) => serial(input.sessionID, async (s) => {
      if (input.lifecycle !== 1 || !input.inferenceID) throw new Error("Missing native inference boundary")
      if (output.messages.some((message) => message.parts.some((part) =>
        part.metadata?.metalanguage?.kind === "directory_agents") && !s.owned.has(message.info.id))) {
        throw new Error("Unknown managed context identity")
      }
      let epoch = s.epochs.get(input.inferenceID)
      if (epoch) {
        if (s.current !== input.inferenceID) throw new Error("Superseded inference projection")
        output.messages.splice(0, output.messages.length, ...structuredClone(epoch.messages))
        return
      }
      if (s.pending) throw new Error("Overlapping unacknowledged inference")
      const sequence = add(s.sequence, 1n)
      const ordinal = add(s.submitted, 1n)
      const retained = [...s.active.values()].filter((entry) => entry.expires >= ordinal)
      const ids = new Set(retained.map((entry) => entry.id))
      const messages = output.messages.filter((message) => !s.owned.has(message.info.id))
      if (messages.some((message) => message.info.sessionID !== input.sessionID)) throw new Error("Mixed managed sessions")
      const positions = new Set(messages.map((message) => message.info.id))
      if (positions.size !== messages.length) throw new Error("Duplicate conversation identity")
      const anchor = messages.at(-1)
      const user = messages.findLast((message) => message.info.role === "user")
      if (!anchor || !user) throw new Error("Managed context has no conversation anchor")
      const groups = new Map()
      for (const entry of retained) {
        if (!entry.message) {
          if (anchor.parts.some((part) => part.type === "tool" && !["completed", "error"].includes(part.state?.status))) {
            throw new Error("Managed context requires completed tool results")
          }
          entry.anchorID = anchor.info.id
          entry.message = {
            info: { id: entry.id, sessionID: input.sessionID, role: "user", time: { created: entry.created },
              agent: user.info.agent, model: { ...user.info.model } },
            parts: [{ id: "prt_" + entry.id, sessionID: input.sessionID, messageID: entry.id, type: "text", synthetic: true,
              metadata: { metalanguage: { kind: "directory_agents", id: entry.id, callID: entry.callID, phase: entry.phase } },
              text: "[Metalanguage automatic directory context; synthetic user-role message, not a new human request.]\n\n" + entry.context }],
          }
        }
        if (!positions.has(entry.anchorID)) throw new Error("Managed context anchor disappeared")
        const group = groups.get(entry.anchorID) ?? []
        group.push(entry.message)
        groups.set(entry.anchorID, group)
      }
      const projected = messages.flatMap((message) => [message, ...(groups.get(message.info.id) ?? [])])
      epoch = { ordinal, revision: s.revision, acknowledged: false, blocked: undefined, admitted: new Map(),
        messages: structuredClone(projected), retained: ids }
      await audit(input.sessionID, { event: "request_snapshot", inference: input.inferenceID, step: String(ordinal),
        revision: String(s.revision), retained: [...ids], excluded: [...s.owned.keys()].filter((id) => !ids.has(id)) })
      s.sequence = sequence
      s.current = input.inferenceID
      s.pending = true
      s.epochs.set(input.inferenceID, epoch)
      output.messages.splice(0, output.messages.length, ...structuredClone(projected))
    }),
    "experimental.chat.inference": async (input, output) => serial(input.sessionID, async (s) => {
      const epoch = s.epochs.get(input.inferenceID)
      if (!epoch || s.current !== input.inferenceID) throw new Error("Unknown managed inference")
      output.required = true
      // A retry before response metadata reuses this snapshot. After metadata,
      // another submission is a different sampling step and needs a new ID.
      if (input.phase === "prepare") {
        if (epoch.acknowledged) throw new Error("Acknowledged inference cannot be resubmitted")
        return
      }
      if (input.phase !== "acknowledged" || !input.responseID) throw new Error("Invalid inference acknowledgement")
      if (epoch.acknowledged) {
        await audit(input.sessionID, { event: "retry_acknowledged", inference: input.inferenceID, response: input.responseID })
        return
      }
      const expired = [...s.active.values()].filter((entry) => !epoch.retained.has(entry.id))
      const revision = expired.length ? add(s.revision, 1n) : s.revision
      await audit(input.sessionID, { event: "acknowledgement_prepared", inference: input.inferenceID, response: input.responseID,
        step: String(epoch.ordinal), revision: String(revision), expired: expired.map((entry) => entry.id) })
      for (const entry of expired) s.active.delete(entry.path)
      s.submitted = epoch.ordinal
      s.revision = revision
      epoch.revision = revision
      epoch.acknowledged = true
      s.pending = false
      await audit(input.sessionID, { event: "acknowledged", inference: input.inferenceID,
        response: input.responseID, step: String(epoch.ordinal), revision: String(s.revision) })
    }),
    "tool.execute.before": async (input, output) => {
      if (!await access(input, output.args, false)) throw new Error(neutral)
    },
    "tool.execute.after": async (input) => { await access(input, input.args, true) },
  }
}
`

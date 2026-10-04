import { randomUUID } from "node:crypto"
import { fingerprint } from "./client.mjs"

export function modelID(model) {
  if (!model || typeof model.providerID !== "string" || typeof model.id !== "string") return null
  return `${model.providerID}/${model.id}`
}

const basePayload = (kind, requestKind, model) => ({ observation_kind: kind, request_kind: requestKind,
  model: model ?? null, http_status: null, attempt: null, retry: null, coverage_status: "limited_hook_coverage" })

export class Connector {
  constructor({ client, directory, session, version }) {
    if (!/^2\./.test(version)) throw new Error("Tarkado connector supports OpenCode V2 only.")
    this.client = client
    this.directory = directory
    this.location = fingerprint(directory)
    this.session = session
    this.tasks = new Map()
    this.queue = []
    this.problem = null
    this.configuration = null
    this.chain = Promise.resolve()
    this.flushing = null
    this.capturing = new Set()
    this.closed = false
    this.connecting = null
  }
  async connect() {
    if (this.connecting) return this.connecting
    this.connecting = this.connectOnce().finally(() => { this.connecting = null })
    return this.connecting
  }
  async connectOnce() {
    const status = await this.client.call("status", { location_sha256: this.location })
    this.configuration = status
    // Reloaded/open tasks have an unobserved interval. They are never silently complete.
    for (const state of status.open_tasks ?? []) {
      if (!state.session_ref || this.tasks.has(state.session_ref)) continue
      this.tasks.set(state.session_ref, state)
      this.enqueue(state.session_ref, basePayload("gap", "unknown", null))
    }
    for (const state of status.recent_tasks ?? []) {
      if (state.session_ref && !this.tasks.has(state.session_ref)) this.tasks.set(state.session_ref, state)
    }
    // Retain every open/queued task; evict only old closed display records.
    for (const [key, state] of this.tasks) {
      if (this.tasks.size <= 128) break
      if (state.closed && !this.queue.some(entry => entry.key === key)) this.tasks.delete(key)
    }
    if (!this.queue.length) this.problem = null
    await this.flush()
    return status
  }
  async scoped(sessionID) {
    const session = await this.session.get({ sessionID }, { signal: AbortSignal.timeout(1000) })
    if (session.location?.directory !== this.directory || session.parentID || session.fork) {
      throw new Error("Only explicit root sessions in the paired exact directory are supported. Child/fork attribution is unavailable.")
    }
    return session
  }
  async start(input) {
    return this.serial(async () => {
      if (!this.configuration) await this.connect()
      await this.scoped(input.sessionID)
      const key = fingerprint(input.sessionID)
      if (this.tasks.has(key)) throw new Error("End the current explicit Tarkado task before starting another.")
      const state = await this.client.call("start", { client_task_id: input.clientTaskID ?? randomUUID(),
        session_ref: key, location_sha256: this.location, task_label: input.taskLabel, boundary: "new_task",
        selected_model: input.selectedModel, task_type: input.taskType ?? null, risk_tags: input.riskTags ?? [],
        required_tools: input.requiredTools ?? [], context_tokens: input.contextTokens ?? null })
      this.tasks.set(key, state)
      return state
    })
  }
  serial(operation) {
    const result = this.chain.then(operation)
    this.chain = result.catch(() => {})
    return result
  }
  enqueue(key, payload) {
    const state = this.tasks.get(key)
    if (!state) return
    if (this.queue.length >= 256) {
      this.problem = "Observation queue full; a coverage gap will be retained. Manual selection is unchanged."
      state.lost = (state.lost ?? 0) + 1
      return
    }
    if (state.lost) {
      state.sequence += state.lost
      state.lost = 0
    }
    state.sequence += 1
    // Project fixed metadata only; hook drafts and prompts never enter the queue.
    const allowed = new Set(this.configuration?.collection_fields ?? [])
    for (const field of ["http_status", "attempt", "retry"]) if (!allowed.has(field)) payload[field] = null
    if (!allowed.has("actual_model")) payload.model = null
    this.queue.push({ key, body: { connector_task_ref: state.connector_task_ref, location_sha256: this.location,
      event_id: randomUUID(), sequence: state.sequence, payload } })
  }
  async flush() {
    if (this.flushing) return this.flushing
    this.flushing = (async () => {
      while (this.queue.length) {
        const entry = this.queue[0]
        try {
          const updated = await this.client.call("observation", entry.body)
          const old = this.tasks.get(entry.key)
          if (old) this.tasks.set(entry.key, { ...updated, sequence: Math.max(old.sequence, updated.sequence), lost: old.lost })
          this.queue.shift()
          this.problem = null
        } catch {
          this.problem = "Observation delivery unavailable/refused. Pending metadata retained in memory; manual choice unchanged."
          return
        }
      }
    })().finally(() => { this.flushing = null })
    return this.flushing
  }
  async capture(event, kind) {
    if (this.closed) return
    const pending = this.captureOne(event, kind)
    this.capturing.add(pending)
    try { await pending } finally { this.capturing.delete(pending) }
  }
  async captureOne(event, kind) {
    let key, original
    try {
      key = fingerprint(event.sessionID)
      original = this.tasks.get(key)
      if (!original || original.closed) return
      await this.scoped(event.sessionID)
      if (this.tasks.get(key)?.connector_task_ref !== original.connector_task_ref || this.tasks.get(key)?.closed) {
        this.problem = "Late observation crossed an explicit boundary; attribution refused."
        return
      }
      const requestKind = event.kind ?? "primary"
      if (!["primary", "compaction", "title", "generate"].includes(requestKind) && !(kind === "retry" && requestKind === "unknown")) throw new Error("Unknown request kind")
      const payload = basePayload(kind, requestKind, modelID(event.model))
      if (kind === "http_status") payload.http_status = event.response.status
      if (kind === "retry") { payload.attempt = event.attempt; payload.retry = event.decision.retry }
      const allowed = new Set(this.configuration?.collection_fields ?? [])
      if (kind === "http_status" && !allowed.has("http_status") || kind === "retry" && (!allowed.has("attempt") || !allowed.has("retry"))) return
      this.enqueue(key, payload)
      // Network delivery is not awaited by OpenCode provider hooks.
      void this.flush()
    } catch {
      if (key && this.tasks.get(key)?.connector_task_ref === original?.connector_task_ref && !this.tasks.get(key)?.closed) this.enqueue(key, { ...basePayload("gap", "unknown", null), coverage_status: "incomplete" })
      this.problem = "Unsupported/wrong-location observation; gap retained, no prompt/provider data collected."
    }
  }
  async state(sessionID) {
    await this.scoped(sessionID)
    const key = fingerprint(sessionID)
    const local = this.tasks.get(key)
    if (!local) return { task: null, problem: this.problem, configured: !!this.configuration }
    await this.flush()
    const current = await this.client.call("task", { connector_task_ref: local.connector_task_ref, location_sha256: this.location })
    const buffered = this.tasks.get(key)
    if (!buffered || buffered.connector_task_ref !== current.connector_task_ref) {
      return { task: buffered ?? null, problem: "Task boundary changed during refresh; review current state.", configured: true }
    }
    this.tasks.set(key, { ...current, sequence: Math.max(buffered.sequence, current.sequence), lost: buffered.lost })
    return { task: this.tasks.get(key), problem: this.problem, configured: true, pending: this.queue.length }
  }
  async feedback(input) {
    return this.serial(async () => {
      await this.scoped(input.sessionID)
      await this.flush()
      if (this.queue.length) throw new Error("Deliver pending observations before recording feedback.")
      const key = fingerprint(input.sessionID)
      const state = this.tasks.get(key)
      if (!state) throw new Error("Start an explicit Tarkado task first.")
      const current = await this.client.call("task", { connector_task_ref: state.connector_task_ref, location_sha256: this.location })
      const updated = await this.client.call("feedback", { connector_task_ref: current.connector_task_ref, location_sha256: this.location,
        action: input.action, expected_revision: input.expectedRevision, value: input.value })
      this.tasks.set(key, updated)
      return updated
    })
  }
  async close(sessionID) {
    return this.serial(async () => {
      await this.scoped(sessionID)
      const key = fingerprint(sessionID)
      if (!this.tasks.has(key)) throw new Error("No explicit task to close.")
      await Promise.all([...this.capturing])
      if (this.tasks.get(key).closed) return this.tasks.get(key)
      this.enqueue(key, basePayload("close", "unknown", null))
      await this.flush()
      if (this.queue.length) throw new Error("Close is pending delivery; do not start another task.")
      const state = this.tasks.get(key)
      // Keep closed task visible for feedback until the user explicitly starts the next one.
      return state
    })
  }
  async newTask(input) {
    const key = fingerprint(input.sessionID)
    if (this.capturing.size) throw new Error("Wait for pending metadata capture before changing explicit task boundaries.")
    const previous = this.tasks.get(key)
    if (previous?.closed && !this.queue.some(item => item.key === key)) this.tasks.delete(key)
    try { return await this.start(input) }
    catch (error) { if (previous && !this.tasks.has(key)) this.tasks.set(key, previous); throw error }
  }
  unload() {
    // No disk spool of prompts/tokens. A restart recovers open records with an explicit gap.
    this.problem = "Connector unloaded; any unshipped observations are a coverage gap on reconnect."
    this.closed = true
  }
}

// Release-pinned V2 before/after identity; no arguments/output/exception text read.
import { createHash, createHmac, randomUUID } from "node:crypto"

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value
const fingerprint = value => createHash("sha256").update(JSON.stringify(canonical(value))).digest("hex")

export class ToolCapture {
  constructor({ company, adapter, location, clock = () => new Date().toISOString(), limit = 256 }) {
    this.company = company
    this.adapter = adapter
    this.location = location
    this.clock = clock
    this.limit = limit
    this.sequence = 0
    this.queue = []
    this.invocations = new Map()
    this.flushing = null
    this.lost = 0
    this.failed = false
    this.closed = false
  }

  identity(event) {
    if (event.sessionID !== this.adapter.sessionID) return null
    if (typeof event.messageID !== "string" || !event.messageID || typeof event.id !== "string" || !event.id || typeof event.tool !== "string") {
      this.gap(); return null
    }
    const tool = this.adapter.binding.local_tools?.find(tool => tool.name === event.tool)
    if (!tool) { this.gap(); return null }
    const ref = createHmac("sha256", this.adapter.binding.task_token)
      .update(JSON.stringify([event.sessionID, event.messageID, event.id, event.tool])).digest("hex")
    return { ref, tool, contract: fingerprint(tool) }
  }

  payload(identity, phase, status, source) {
    return { tool_invocation_ref: identity?.ref ?? null, tool_contract_ref: identity?.contract ?? null,
      tool_phase: phase, tool_status: status, tool_observed_at: this.clock(), tool_attempt_ref: null, tool_status_source: source }
  }

  enqueue(payload) {
    this.sequence++
    if (this.queue.length >= this.limit) { this.lost++; return }
    this.queue.push({ connector_task_ref: this.adapter.descriptor.connectorTaskRef, location_sha256: this.location,
      session_ref: this.adapter.sessionHash, event_id: randomUUID(), sequence: this.sequence, payload })
  }

  gap() { this.enqueue(this.payload(null, "gap", "gap", "delivery_gap")) }

  async open() {
    this.enqueue(this.payload(null, "open", "capture_open", "adapter_lifecycle"))
    await this.flush()
    if (this.failed) throw new Error("Capture initialization unavailable; inspect retained task/budget, do not repeat a claim.")
  }

  before(event) {
    const identity = this.identity(event)
    if (!identity) { void this.flush(); return }
    if (this.closed) { this.gap(); void this.flush(); return }
    if (this.invocations.has(identity.ref)) return // No new event/observation on an exact hook retry.
    if (this.invocations.size >= this.limit) { this.gap(); void this.flush(); return }
    this.invocations.set(identity.ref, { identity, result: null })
    this.enqueue(this.payload(identity, "start", "started", "opencode_v2_hook"))
    void this.flush()
  }

  after(event) {
    const identity = this.identity(event)
    if (!identity) { void this.flush(); return }
    let invocation = this.invocations.get(identity.ref)
    if (!invocation) {
      this.gap() // No invented before/completion identity on a missed hook.
      if (this.invocations.size >= this.limit) { void this.flush(); return }
      invocation = { identity, result: null }
      this.invocations.set(identity.ref, invocation)
    }
    let status = event.status === "error" ? "execution_error" : event.status === "completed" && event.result != null ? "completed" : "unknown"
    let source = "opencode_v2_hook"
    if (identity.tool.status_metadata_key === "tarkado_status_v1") {
      // This key is OUR explicit reviewed tool contract, not a claimed native
      // test/permission/cancellation field. Only this fixed enum is projected.
      const metadata = event.status === "completed" ? event.result?.metadata : event.status === "error" ? event.error?.metadata : null
      const signal = metadata?.tarkado_status_v1
      if (signal && typeof signal === "object" && Object.keys(signal).sort().join(",") === "schema_version,status" && signal.schema_version === 1
        && ["test_failed", "permission_refused", "interrupted"].includes(signal.status)
        && (signal.status !== "test_failed" || identity.tool.capability === "test")) {
        status = signal.status; source = "reviewed_tool_metadata"
      }
    }
    const result = JSON.stringify([status, source])
    if (invocation.result === result) return
    if (invocation.result && invocation.result !== JSON.stringify(["unknown", "missing_after_hook"])) { this.gap(); return }
    invocation.result = result
    this.enqueue(this.payload(identity, "result", status, source))
    void this.flush()
  }

  missing() {
    for (const invocation of this.invocations.values()) if (invocation.result === null) {
      invocation.result = JSON.stringify(["unknown", "missing_after_hook"])
      this.enqueue(this.payload(invocation.identity, "result", "unknown", "missing_after_hook"))
    }
  }

  async flush() {
    if (this.flushing) return this.flushing
    this.flushing = (async () => {
      while (this.queue.length || this.lost) {
        if (this.lost && this.queue.length < this.limit) {
          this.lost = 0
          this.gap() // Sequence holes permanently account for all dropped events.
        }
        const event = this.queue[0]
        try { await this.company.call("tool-status", event) }
        catch { this.failed = true; return }
        this.queue.shift()
      }
      this.failed = false
    })().finally(() => { this.flushing = null })
    return this.flushing
  }

  async barrier() {
    this.missing()
    await this.flush()
    if (this.failed || this.queue.length || this.lost) throw new Error("Tool-status delivery unavailable; refuse unsafe paid continuation and preserve metadata gaps.")
  }
}

// Joined explicit task → scoped selection → new session. No prompt submission.
import { randomUUID } from "node:crypto"
import { FreshSessionDeliveryAdapter } from "./delivery-adapter.mjs"
import { BoundarySelection } from "./boundary-selection.mjs"
import { fingerprint } from "./client.mjs"
import { ToolCapture } from "./tool-capture.mjs"

export class DeliveryCoordinator {
  constructor({ company, session, directory, gatewayRef, providerID, gatewayOrigin, toolFailureCapture = false }) {
    this.company = company
    this.session = session
    this.location = fingerprint(directory)
    this.directory = directory
    this.options = { company, session, gatewayRef, providerID, gatewayOrigin }
    this.adapters = new Map()
    this.links = new Map()
    this.starts = new Map()
    this.toolFailureCapture = toolFailureCapture
    this.captures = new Map()
    this.recoveryGaps = new Map()
  }

  async connect() {
    const result = await this.company.call("delivery-options", { location_sha256: this.location })
    if (this.toolFailureCapture && result.tool_capture_approved) {
      for (const task of result.tool_capture_tasks ?? []) {
        if ([...this.captures.values()].some(capture => capture.adapter.descriptor.connectorTaskRef === task.connector_task_ref)) continue
        let gap = this.recoveryGaps.get(task.connector_task_ref)
        if (gap === true) continue
        if (!gap) {
          gap = { connector_task_ref: task.connector_task_ref, session_ref: task.session_ref, location_sha256: this.location,
            event_id: randomUUID(), sequence: task.sequence + 1, payload: { tool_invocation_ref: null, tool_contract_ref: null,
              tool_phase: "gap", tool_status: "gap", tool_observed_at: new Date().toISOString(), tool_attempt_ref: null, tool_status_source: "delivery_gap" } }
          this.recoveryGaps.set(task.connector_task_ref, gap)
        }
        await this.company.call("tool-status", gap)
        this.recoveryGaps.set(task.connector_task_ref, true)
      }
    }
    return { ...result, gateway_ref: this.options.gatewayRef }
  }

  async newTask(input) {
    if (Object.hasOwn(input, "sessionID")) throw new Error("Delivery cannot reuse or switch an active session.")
    if (this.toolFailureCapture && !(await this.connect()).tool_capture_approved) throw new Error("Explicit tool-status collection approval/new pairing is required before enabling capture.")
    const clientTaskID = input.clientTaskID ?? randomUUID()
    if (this.starts.has(clientTaskID)) throw new Error("This explicit start was already submitted. Inspect its retained task; do not mint another claim on a retry.")
    this.starts.set(clientTaskID, true)
    const adapter = new FreshSessionDeliveryAdapter({ ...this.options, outputLimit: input.outputLimit })
    const linked = await this.company.call("start", { client_task_id: clientTaskID, session_ref: adapter.pendingSessionReference(),
      location_sha256: this.location, task_label: input.taskLabel, task_type: input.taskType, risk_tags: input.riskTags,
      selected_model: input.selectedModel, required_tools: input.requiredTools ?? [], context_tokens: input.contextTokens, boundary: "new_task" })
    this.links.set(adapter.pendingSessionReference(), linked.connector_task_ref)
    const request = { selection_id: randomUUID(), task: linked.conditional_task_request,
      repository_ref: input.repositoryRef, boundary: "new_task", reserve_usd: input.taskCapUSD, override_model: input.overrideModel ?? null }
    adapter.setDescriptor({ request, scopeRef: input.scopeRef, connectorTaskRef: linked.connector_task_ref,
      locationHash: this.location, sessionRef: linked.session_ref })
    const result = await new BoundarySelection({ company: this.company, adapter }).prepare({ scopeRef: input.scopeRef,
      locationHash: this.location, connectorTaskRef: linked.connector_task_ref, request })
    if (!result.modelApplied) return { ...result, task: linked, sessionCreated: false }
    this.adapters.set(adapter.sessionID, adapter)
    if (this.toolFailureCapture && adapter.binding.local_tools?.length) {
      const capture = new ToolCapture({ company: this.company, adapter, location: this.location })
      this.captures.set(adapter.sessionID, capture)
      await capture.open()
    }
    return { sessionID: adapter.sessionID, model: result.selection.model, task: linked,
      sessionCreated: true, executionSent: false, note: "New isolated session only. No prompt was submitted; current work was not changed." }
  }

  async request(event) {
    const adapter = this.adapters.get(event.sessionID)
    if (adapter) {
      const capture = this.captures.get(event.sessionID)
      if (capture) await capture.barrier()
      await adapter.request(event)
    }
  }

  websocket(event) { this.adapters.get(event.sessionID)?.websocket(event) }

  toolBefore(event) { this.captureTool(event, "before") }
  toolAfter(event) { this.captureTool(event, "after") }
  captureTool(event, phase) {
    const capture = this.captures.get(event.sessionID)
    if (!capture) return
    try { capture[phase](event) }
    catch { capture.gap(); void capture.flush() } // Never change a tool result or retain private exception text.
  }
  async captureUnload() {
    for (const capture of this.captures.values()) if (!capture.closed) { capture.missing(); capture.gap(); await capture.flush() }
  }

  prepareOptions(event) {
    const adapter = this.adapters.get(event.sessionID)
    if (adapter) adapter.prepareOptions(event)
  }

  async state(sessionID) {
    const ref = this.links.get(fingerprint(sessionID))
    if (!ref) return { task: null, delivery: null, executionSent: false, problem: "No task bound by this source instance. Use the company browser for interrupted/restarted task recovery." }
    return this.company.call("delivery-task", { connector_task_ref: ref, location_sha256: this.location })
  }

  async feedback(input) {
    const ref = this.links.get(fingerprint(input.sessionID))
    if (!ref) throw new Error("This source instance does not own the requested task.")
    return this.company.call("feedback", { connector_task_ref: ref, location_sha256: this.location,
      action: input.action, expected_revision: input.expectedRevision, value: input.value })
  }

  async end(sessionID) {
    const adapter = this.adapters.get(sessionID)
    if (!adapter) throw new Error("No new delivery task belongs to this source instance; use browser interrupted-close recovery.")
    const capture = this.captures.get(sessionID)
    if (capture) await capture.barrier()
    const host = await this.session.get({ sessionID })
    if (host.location?.directory !== this.directory || host.parentID || host.fork) throw new Error("End only this exact paired root task.")
    const ref = adapter.descriptor.connectorTaskRef
    const task = await this.company.call("task", { connector_task_ref: ref, location_sha256: this.location })
    if (task.closed) { if (capture) capture.closed = true; return task }
    // A repeated close after a lost response uses exactly the same event identity.
    adapter.closeEvent ??= { connector_task_ref: ref, location_sha256: this.location, event_id: randomUUID(),
      sequence: task.sequence + 1, payload: { observation_kind: "close", request_kind: "unknown", model: null,
        http_status: null, attempt: null, retry: null, coverage_status: "limited_hook_coverage" } }
    const result = await this.company.call("observation", adapter.closeEvent)
    if (capture) capture.closed = true
    return result
  }
}

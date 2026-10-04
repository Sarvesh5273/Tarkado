// Joined explicit task → scoped selection → new session. No prompt submission.
import { randomUUID } from "node:crypto"
import { FreshSessionDeliveryAdapter } from "./delivery-adapter.mjs"
import { BoundarySelection } from "./boundary-selection.mjs"
import { fingerprint } from "./client.mjs"

export class DeliveryCoordinator {
  constructor({ company, session, directory, gatewayRef, providerID, gatewayOrigin }) {
    this.company = company
    this.session = session
    this.location = fingerprint(directory)
    this.directory = directory
    this.options = { company, session, gatewayRef, providerID, gatewayOrigin }
    this.adapters = new Map()
    this.links = new Map()
    this.starts = new Map()
  }

  async connect() {
    const result = await this.company.call("delivery-options", { location_sha256: this.location })
    return { ...result, gateway_ref: this.options.gatewayRef }
  }

  async newTask(input) {
    if (Object.hasOwn(input, "sessionID")) throw new Error("Delivery cannot reuse or switch an active session.")
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
    return { sessionID: adapter.sessionID, model: result.selection.model, task: linked,
      sessionCreated: true, executionSent: false, note: "New isolated session only. No prompt was submitted; current work was not changed." }
  }

  async request(event) {
    const adapter = this.adapters.get(event.sessionID)
    if (adapter) await adapter.request(event)
  }

  websocket(event) { this.adapters.get(event.sessionID)?.websocket(event) }

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
    const host = await this.session.get({ sessionID })
    if (host.location?.directory !== this.directory || host.parentID || host.fork) throw new Error("End only this exact paired root task.")
    const ref = adapter.descriptor.connectorTaskRef
    const task = await this.company.call("task", { connector_task_ref: ref, location_sha256: this.location })
    if (task.closed) return task
    // A repeated close after a lost response uses exactly the same event identity.
    adapter.closeEvent ??= { connector_task_ref: ref, location_sha256: this.location, event_id: randomUUID(),
      sequence: task.sequence + 1, payload: { observation_kind: "close", request_kind: "unknown", model: null,
        http_status: null, attempt: null, retry: null, coverage_status: "limited_hook_coverage" } }
    return this.company.call("observation", adapter.closeEvent)
  }
}

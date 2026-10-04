// A separately trusted delivery integration seam, not an OpenCode switchModel shortcut.
// This is intentionally not registered by the observe-only plugin entrypoint.
export class UnsupportedBoundaryAdapter {
  async inspect() { throw new Error("Atomic new-task/model/provider-cap admission is not supported by this OpenCode observer.") }
  async bind() { throw new Error("Observe-only connector cannot bind an automatic model selection to provider delivery.") }
}

const canonical = value => {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
  return value
}

export class BoundarySelection {
  constructor({ company, adapter = new UnsupportedBoundaryAdapter() }) {
    this.company = company
    this.adapter = adapter
  }
  async prepare({ scopeRef, locationHash, connectorTaskRef, request }) {
    // inspect must be read-only; it validates an existing new-task boundary without dispatching it.
    const boundary = await this.adapter.inspect(request)
    if (!boundary || boundary.requestID !== request.selection_id || boundary.newTask !== true || boundary.capEnforced !== true
      || boundary.atomicModelBinding !== true) throw new Error("Trusted atomic admission capability is unavailable; retain manual choice.")
    const result = await this.company.call("conditional-select", { scope_ref: scopeRef, location_sha256: locationHash, connector_task_ref: connectorTaskRef, selection_request: request })
    if (result.status !== "selected" || result.historical_replay || !result.new_reservation) return { ...result, modelApplied: false }
    const selection = result.selection
    if (selection.selection_id !== request.selection_id || JSON.stringify(canonical(selection.request)) !== JSON.stringify(canonical(request))) {
      throw new Error("Selection response differs from the inspected exact task/model/reservation scope.")
    }
    const claim = await this.company.call("conditional-claim", { scope_ref: scopeRef, location_sha256: locationHash, selection_id: request.selection_id })
    if (!claim.new_claim || claim.historical_replay || claim.model !== selection.model || claim.max_cost_usd !== selection.reserve_usd) {
      throw new Error("Selection was already consumed or changed; no automatic model binding.")
    }
    // A real approved adapter must own an atomic task descriptor/provider-cap boundary.
    // bind must not send a prompt, start a model request, or edit an already-running session.
    await this.adapter.bind(boundary, { model: selection.model, maxCostUSD: selection.reserve_usd, selectionID: selection.selection_id })
    return { ...result, modelApplied: true, executionSent: false,
      note: "Model bound to the inspected new-task descriptor only; provider delivery remains the trusted adapter's responsibility." }
  }
}

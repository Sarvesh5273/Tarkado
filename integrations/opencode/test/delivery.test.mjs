import test from "node:test"
import assert from "node:assert/strict"
import { FreshSessionDeliveryAdapter, registerDeliveryHooks } from "../src/delivery-adapter.mjs"
import { BoundarySelection } from "../src/boundary-selection.mjs"
import { DeliveryCoordinator } from "../src/delivery-coordinator.mjs"

function setup() {
  const calls = []
  const request = { selection_id: "controlled-selection", boundary: "new_task", repository_ref: "synthetic", task: {}, reserve_usd: "0.10", override_model: null }
  const choice = { model: "fixture/cheap", maxCostUSD: "0.10", selectionID: request.selection_id }
  let adapter
  const company = { async call(method, value) {
    calls.push({ method, value })
    if (method === "delivery-preflight") return { requestID: request.selection_id, newTask: true, capEnforced: true, atomicModelBinding: true }
    if (method === "conditional-select") return { status: "selected", new_reservation: true, historical_replay: false,
      selection: { selection_id: request.selection_id, request, model: choice.model, reserve_usd: choice.maxCostUSD } }
    if (method === "conditional-claim") return { new_claim: true, historical_replay: false, model: choice.model, max_cost_usd: choice.maxCostUSD }
    return { binding_ref: "controlled-binding", task_token: "synthetic-private-task-token", model: choice.model,
      task_cap_usd: choice.maxCostUSD, gateway_model: "company-cheap", provider_model: "controlled-provider", session_ref: adapter.pendingSessionReference() }
  } }
  const session = { async create(value) { calls.push({ method: "create", value }); return { ...value } } }
  adapter = new FreshSessionDeliveryAdapter({ company, session, gatewayRef: "controlled-gateway", providerID: "company", gatewayOrigin: "https://gateway.company.example" })
  adapter.setDescriptor({ request, scopeRef: "controlled-scope", connectorTaskRef: "controlled-task", locationHash: "a".repeat(64), sessionRef: adapter.pendingSessionReference() })
  return { adapter, request, choice, calls, company }
}

test("concrete fresh-session adapter joins selection claim binding and create without prompting", async () => {
  const { adapter, request, company, calls } = setup()
  const result = await new BoundarySelection({ company, adapter }).prepare({ scopeRef: "controlled-scope", connectorTaskRef: "controlled-task", locationHash: "a".repeat(64), request })
  assert.equal(result.modelApplied, true)
  assert.equal(result.executionSent, false)
  assert.deepEqual(calls.map(x => x.method), ["delivery-preflight", "conditional-select", "conditional-claim", "delivery-bind", "create"])
  assert.deepEqual(calls.at(-1).value.model, { providerID: "company", id: "company-cheap" })
  await assert.rejects(adapter.inspect(request), /unused explicit/)
})

test("binding an existing descriptor or changed model cannot create another session", async () => {
  const { adapter, request, choice } = setup()
  await assert.rejects(adapter.inspect({ ...request, boundary: "continuation" }), /new-task/)
  await assert.rejects(adapter.bind(await adapter.inspect(request), { ...choice, model: "wrong-model" }), /binding differs/)
  await assert.rejects(adapter.bind({ requestID: request.selection_id }, choice), /consumed/)
})

test("native request adds only scoped metadata and exact duplicate retry identity", async () => {
  const { adapter, request, choice } = setup()
  await adapter.bind(await adapter.inspect(request), choice)
  const make = () => ({ sessionID: adapter.sessionID, kind: "title", model: adapter.binding.model,
    request: new Request("https://gateway.company.example/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "company-cheap", messages: [{ role: "user", content: "synthetic private prompt" }], max_completion_tokens: 1000 }) }) })
  const first = make(), retry = make()
  await adapter.request(first); await adapter.request(retry)
  const left = await first.request.json(), right = await retry.request.json()
  assert.equal(left.metadata.tarkado_request, right.metadata.tarkado_request)
  assert.equal(left.metadata.tarkado_kind, "title")
  assert.equal(left.model, "company-cheap")
  assert.equal(left.messages[0].content, "synthetic private prompt")
  assert.equal(Object.hasOwn(left.metadata, "prompt"), false)
})

test("unrelated work is untouched while wrong model endpoint and WebSocket are refused", async () => {
  const { adapter, request, choice } = setup()
  await adapter.bind(await adapter.inspect(request), choice)
  const unrelated = { sessionID: "ses_unrelated" }
  await adapter.request(unrelated)
  assert.deepEqual(unrelated, { sessionID: "ses_unrelated" })
  await assert.rejects(adapter.request({ sessionID: adapter.sessionID, model: { providerID: "other", id: "other" } }), /wrong-model/)
  await assert.rejects(adapter.request({ sessionID: adapter.sessionID, model: adapter.binding.model, kind: "primary", request: new Request("https://other.example/v1/chat/completions", { method: "POST" }) }), /exact company/)
  assert.throws(() => adapter.websocket({ sessionID: adapter.sessionID }), /WebSocket/)
})

test("hook registration is explicit and disposal never deletes a session or task", async () => {
  const calls = []
  const { adapter } = setup()
  const dispose = await registerDeliveryHooks({ session: { async hook(name) { calls.push(name); return { async dispose() { calls.push("dispose") } } } } }, adapter)
  assert.deepEqual(calls, ["http.request", "experimental.ws.handshake"])
  await dispose()
  assert.equal(calls.filter(x => x === "dispose").length, 2)
})

test("joined coordinator uses the real source without private session reads or prompts", async () => {
  const calls = []
  let start, selected
  const company = { async call(method, value) {
    calls.push(method)
    if (method === "start") {
      start = value
      return { connector_task_ref: "controlled-task", session_ref: value.session_ref,
        conditional_task_request: { task_id: value.task_label, selected_model: value.selected_model } }
    }
    if (method === "delivery-preflight") return { requestID: value.selection_request.selection_id, newTask: true, capEnforced: true, atomicModelBinding: true }
    if (method === "conditional-select") {
      selected = value.selection_request
      return { status: "selected", new_reservation: true, historical_replay: false,
        selection: { selection_id: selected.selection_id, request: selected, model: "fixture/cheap", reserve_usd: selected.reserve_usd } }
    }
    if (method === "conditional-claim") return { new_claim: true, historical_replay: false, model: "fixture/cheap", max_cost_usd: selected.reserve_usd }
    if (method === "delivery-bind") return { binding_ref: "controlled-binding", task_token: "synthetic-private-token", model: "fixture/cheap",
      task_cap_usd: selected.reserve_usd, session_ref: start.session_ref, gateway_model: "company-cheap" }
    throw new Error("Unexpected operation")
  } }
  const coordinator = new DeliveryCoordinator({ company, directory: "/synthetic/work", gatewayRef: "controlled-gateway", providerID: "company",
    gatewayOrigin: "https://gateway.company.example", session: { async create(value) { calls.push("create"); return value } } })
  const result = await coordinator.newTask({ scopeRef: "controlled-scope", repositoryRef: "synthetic", taskLabel: "Explicit documentation task",
    taskType: "documentation", riskTags: ["low"], selectedModel: "fixture/premium", contextTokens: 2000, taskCapUSD: "0.10", overrideModel: null })
  assert.equal(result.sessionCreated, true)
  assert.equal(result.executionSent, false)
  assert.deepEqual(calls, ["start", "delivery-preflight", "conditional-select", "conditional-claim", "delivery-bind", "create"])
  await assert.rejects(coordinator.newTask({ sessionID: "ses_active" }), /active session/)
})

test("native semantic output cap is made explicit without adding another request", async () => {
  const { adapter, request, choice } = setup()
  await adapter.bind(await adapter.inspect(request), choice)
  const event = { sessionID: adapter.sessionID, kind: "primary", model: adapter.binding.model,
    request: new Request("https://gateway.company.example/v1/chat/completions", { method: "POST", body: JSON.stringify({ model: "company-cheap",
      messages: [{ role: "user", content: "synthetic" }], max_tokens: 1000, stream: true }) }) }
  await adapter.request(event)
  const body = await event.request.json()
  assert.equal(body.max_completion_tokens, 1000)
  assert.equal(Object.hasOwn(body, "max_tokens"), false)
  assert.deepEqual(body.stream_options, { include_usage: true })
})

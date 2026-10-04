import test from "node:test"
import assert from "node:assert/strict"
import { BoundarySelection } from "../src/boundary-selection.mjs"

const request = { selection_id: "test-selection", repository_ref: "synthetic-repository", override_model: null, reserve_usd: "0.1" }
const input = { scopeRef: "test-scope", locationHash: "a".repeat(64), connectorTaskRef: "synthetic-linked-task", request }

test("default observer adapter cannot execute or apply automatic selection", async () => {
  let calls = 0
  const seam = new BoundarySelection({ company: { call: async () => { calls++ } } })
  await assert.rejects(seam.prepare(input), /not supported/)
  assert.equal(calls, 0)
})

test("controlled atomic descriptor binding requires fresh reservation and matching one-use claim", async () => {
  const calls = [], bindings = []
  const selection = { selection_id: request.selection_id, request, model: "fixture/cheap", reserve_usd: "0.1" }
  const company = { async call(method, value) { calls.push({ method, value }); return method === "conditional-select"
    ? { status: "selected", new_reservation: true, historical_replay: false, selection }
    : { new_claim: true, historical_replay: false, model: "fixture/cheap", max_cost_usd: "0.1" } } }
  const adapter = { async inspect() { return { requestID: request.selection_id, newTask: true, capEnforced: true, atomicModelBinding: true } },
    async bind(boundary, value) { bindings.push(value) } }
  const result = await new BoundarySelection({ company, adapter }).prepare(input)
  assert.equal(result.modelApplied, true)
  assert.equal(result.executionSent, false)
  assert.deepEqual(calls.map(item => item.method), ["conditional-select", "conditional-claim"])
  assert.equal(bindings[0].model, "fixture/cheap")
})

test("historical selection cannot reapply a model or repeat provider admission", async () => {
  let binds = 0
  const seam = new BoundarySelection({ company: { async call() { return { status: "selected", new_reservation: false, historical_replay: true } } },
    adapter: { async inspect() { return { requestID: request.selection_id, newTask: true, capEnforced: true, atomicModelBinding: true } }, async bind() { binds++ } } })
  const result = await seam.prepare(input)
  assert.equal(result.modelApplied, false)
  assert.equal(binds, 0)
})

test("changed/consumed claim cannot bind a returned model", async () => {
  let binds = 0
  const selection = { selection_id: request.selection_id, request, model: "fixture/cheap", reserve_usd: "0.1" }
  const seam = new BoundarySelection({ company: { async call(method) { return method === "conditional-select"
    ? { status: "selected", new_reservation: true, historical_replay: false, selection }
    : { new_claim: true, model: "fixture/premium", max_cost_usd: "0.1" } } }, adapter: { async inspect() { return { requestID: request.selection_id, newTask: true, capEnforced: true, atomicModelBinding: true } }, async bind() { binds++ } } })
  await assert.rejects(seam.prepare(input), /already consumed or changed/)
  assert.equal(binds, 0)
})

test("changed task payload cannot be silently bound under an otherwise matching selection", async () => {
  let claimed = 0, bound = 0
  const seam = new BoundarySelection({ company: { async call(method) {
    if (method === "conditional-claim") { claimed++; return {} }
    return { status: "selected", new_reservation: true, selection: { selection_id: request.selection_id,
      request: { ...request, reserve_usd: "100" }, model: "fixture/cheap", reserve_usd: "100" } }
  } }, adapter: { async inspect() { return { requestID: request.selection_id, newTask: true, capEnforced: true, atomicModelBinding: true } }, async bind() { bound++ } } })
  await assert.rejects(seam.prepare(input), /exact task\/model\/reservation/)
  assert.equal(claimed, 0)
  assert.equal(bound, 0)
})

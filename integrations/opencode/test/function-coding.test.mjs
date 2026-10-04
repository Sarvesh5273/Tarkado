import test from "node:test"
import assert from "node:assert/strict"
import { FreshSessionDeliveryAdapter } from "../src/delivery-adapter.mjs"
import { DeliveryCoordinator } from "../src/delivery-coordinator.mjs"
import { deliveryActions } from "../src/delivery-actions.mjs"

const functions = [{ name: "read", capability: "read", function_sha256: "a".repeat(64) }, { name: "edit", capability: "edit", function_sha256: "b".repeat(64) }]

function adapter() {
  const value = new FreshSessionDeliveryAdapter({ company: {}, session: {}, gatewayRef: "controlled", providerID: "company", gatewayOrigin: "https://gateway.company.example", outputLimit: 1000 })
  value.binding = { model: { providerID: "company", id: "company-functions" }, gateway_model: "company-functions", task_token: "synthetic-private-token", binding_ref: "controlled-bound", local_tools: functions }
  return value
}

test("bound outgoing tool inventory filters only this task's reviewed local functions", () => {
  const value = adapter()
  const tools = { read: { input: {} }, edit: { input: {} }, shell: { input: {} }, subagent: { input: {} }, remote_paid: { input: {} } }
  const event = { sessionID: value.sessionID, model: value.binding.model, options: {}, tools: structuredClone(tools) }
  value.prepareOptions(event)
  assert.deepEqual(Object.keys(event.tools), ["read", "edit"])
  assert.equal(event.options.maxTokens, 1000)
  const unrelated = { sessionID: "ses_other", model: {}, options: {}, tools }
  value.prepareOptions(unrelated)
  assert.deepEqual(Object.keys(unrelated.tools), ["read", "edit", "shell", "subagent", "remote_paid"])
})

test("wire request preserves function arguments/results only in inference and retains exact retry identity", async () => {
  const value = adapter()
  const body = { model: "company-functions", max_tokens: 1000, tools: [{ type: "function", function: { name: "read", parameters: { type: "object" } } }],
    messages: [{ role: "user", content: "Synthetic private code task" }, { role: "assistant", content: null,
      tool_calls: [{ id: "call_synthetic", type: "function", function: { name: "read", arguments: "{\"path\":\"synthetic.py\"}" } }] },
      { role: "tool", tool_call_id: "call_synthetic", content: "Synthetic private tool result/source" }] }
  const make = () => ({ sessionID: value.sessionID, kind: "primary", model: value.binding.model,
    request: new Request("https://gateway.company.example/v1/chat/completions", { method: "POST", body: JSON.stringify(body) }) })
  const first = make(), retry = make()
  await value.request(first); await value.request(retry)
  const a = await first.request.json(), b = await retry.request.json()
  assert.deepEqual(a.messages, body.messages)
  assert.deepEqual(a.tools, body.tools)
  assert.equal(a.metadata.tarkado_request, b.metadata.tarkado_request)
  assert.equal(Object.values(a.metadata).some(item => typeof item === "string" && item.includes("Synthetic private")), false)
})

test("unapproved or hosted tools refuse the wire request before gateway delivery", async () => {
  const value = adapter()
  for (const tools of [[{ type: "web_search" }], [{ type: "function", function: { name: "subagent" } }], [{ type: "function", function: { name: "shell" } }]]) {
    const event = { sessionID: value.sessionID, kind: "primary", model: value.binding.model, request: new Request("https://gateway.company.example/v1/chat/completions",
      { method: "POST", body: JSON.stringify({ model: "company-functions", max_tokens: 1000, tools }) }) }
    await assert.rejects(value.request(event), /reviewed local function/)
  }
})

test("coordinator preserves explicit required tool capabilities in task metadata", async () => {
  let started
  const coordinator = new DeliveryCoordinator({ company: { async call(method, value) {
    if (method === "start") { started = value; return { connector_task_ref: "controlled", session_ref: value.session_ref, conditional_task_request: {} } }
    throw new Error("Controlled refusal stops before claim")
  } }, session: {}, directory: "/synthetic", gatewayRef: "controlled", providerID: "company", gatewayOrigin: "https://gateway.company.example" })
  await assert.rejects(coordinator.newTask({ requiredTools: ["read", "edit"], selectedModel: "fixture/premium", outputLimit: 1000 }), /refusal/)
  assert.deepEqual(started.required_tools, ["read", "edit"])
})

test("guided tool declaration accepts only evidenced capabilities and confirms them explicitly", async () => {
  let submitted, route = { type: "home" }, current = { task: null }
  const prompts = ["read, edit", "Synthetic edit task", "2000", "1000", "0.10"], choices = ["scope", "documentation", "fixture/premium", ""]
  const confirms = []
  const context = { location: { directory: "/synthetic" }, ui: { router: { current: () => route, navigate: value => { route = value } },
    toast: { show: () => { throw new Error("Unexpected refusal") } }, dialog: { prompt: async () => prompts.shift(), select: async () => choices.shift(), confirm: async value => { confirms.push(value); return true } } } }
  const rpc = { async connect() { return { source_kind: "team", collection_supported: true, gateway_ref: "gateway", gateways: [{ gateway_ref: "gateway" }],
    models: ["fixture/premium"], repository_ref: "synthetic", scopes: [{ scope_ref: "scope", pilot_id: "Controlled", status: "active", authority_current: true,
      accounting: { remaining_usd: "1.00", remaining_task_slots: 2 }, routes: [{ task_type: "documentation", model: "fixture/cheap", local_tools: functions }] }] } },
    async start(value) { submitted = value; return { sessionCreated: true, executionSent: false, sessionID: "ses_controlled_new" } }, async state() { return { task: null } } }
  await deliveryActions({ rpc, context, status: () => current, setStatus: value => { current = value } }).start()
  assert.deepEqual(submitted.requiredTools, ["read", "edit"])
  assert.ok(confirms.at(-1).message.includes("Required local capabilities: read, edit"))
  assert.equal(submitted.outputLimit, 1000)
})

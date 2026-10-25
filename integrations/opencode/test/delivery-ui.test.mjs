import test from "node:test"
import assert from "node:assert/strict"
import { deliveryActions, deliveryLines } from "../src/delivery-actions.mjs"
import { DeliveryCoordinator } from "../src/delivery-coordinator.mjs"
import { readFile } from "node:fs/promises"
import vm from "node:vm"
import { FreshSessionDeliveryAdapter } from "../src/delivery-adapter.mjs"

function setup() {
  const calls = [], toasts = []
  let current = { type: "session", sessionID: "ses_unrelated_active" }, state = { task: null }
  const prompts = ["Explicit synthetic task", "2000", "1000", "0.10"]
  const selects = ["controlled-scope", "documentation", "fixture/premium", ""]
  const context = { location: { directory: "/synthetic/work" }, data: { session: { status: () => ({ type: "idle" }) } }, ui: {
    router: { current: () => current, navigate: route => { current = route; calls.push({ method: "navigate", route }) } },
    toast: { show: value => toasts.push(value) }, dialog: { select: async () => selects.shift(), prompt: async () => prompts.shift(), confirm: async () => true },
  } }
  const config = { source_kind: "team", collection_supported: true, gateway_ref: "controlled-gateway", repository_ref: "synthetic",
    gateways: [{ gateway_ref: "controlled-gateway" }], models: ["fixture/premium", "fixture/cheap"], scopes: [{ scope_ref: "controlled-scope",
      pilot_id: "Controlled pilot", status: "active", authority_current: true, routes: [{ task_type: "documentation", model: "fixture/cheap" }],
      accounting: { remaining_usd: "1.00", remaining_task_slots: 3 } }] }
  const rpc = { async connect() { return config }, async start(input) { calls.push({ method: "start", input }); return { sessionCreated: true, executionSent: false, sessionID: "ses_new_bound" } },
    async state(input) { calls.push({ method: "state", input }); return { task: null } }, async end(input) { calls.push({ method: "end", input }) } }
  const actions = deliveryActions({ rpc, context, status: () => state, setStatus: value => { state = value } })
  return { actions, rpc, context, config, calls, toasts, changeRoute: value => { current = value } }
}

test("guided delivery start creates only a fresh root and navigates without changing existing model", async () => {
  const { actions, calls, toasts } = setup()
  await actions.start()
  assert.equal(toasts.length, 0)
  assert.deepEqual(calls.map(x => x.method), ["start", "navigate", "state"])
  assert.equal(calls[0].input.outputLimit, 1000)
  assert.equal(calls[0].input.taskCapUSD, "0.10")
  assert.equal(calls[0].input.selectedModel, "fixture/premium")
  assert.equal(Object.hasOwn(calls[0].input, "sessionID"), false)
  assert.deepEqual(calls[1].route, { type: "session", sessionID: "ses_new_bound" })
})

test("dialog cancellation route change and unconfigured scopes never start provider or reserve", async () => {
  const cancelled = setup()
  cancelled.context.ui.dialog.confirm = async () => false
  await cancelled.actions.start()
  assert.equal(cancelled.calls.length, 0)
  const changed = setup()
  changed.context.ui.dialog.confirm = async () => { changed.changeRoute({ type: "home" }); return true }
  await changed.actions.start()
  assert.equal(changed.calls.length, 0)
  assert.equal(changed.toasts.length, 1)
  const unavailable = setup(); unavailable.config.scopes[0].authority_current = false
  await unavailable.actions.start()
  assert.equal(unavailable.calls.length, 0)
})

test("delivery end refuses unknown or running sessions instead of releasing their cost", async () => {
  const { actions, context, calls, toasts } = setup()
  context.data.session.status = () => ({ type: "running" })
  await actions.end()
  assert.equal(calls.length, 0)
  assert.equal(toasts.length, 1)
  // OpenCode 2.0.21's TUI returns bare strings; anything but explicit idle refuses.
  for (const value of ["busy", "running", "retry", undefined, {}]) {
    context.data.session.status = () => value
    await actions.end()
  }
  assert.equal(calls.length, 0)
  assert.equal(toasts.length, 6)
  context.data.session.status = () => "idle"
  await actions.end()
  assert.deepEqual(calls[0], { method: "end", input: { sessionID: "ses_unrelated_active" } })
  assert.equal(toasts.length, 6)
})

test("task panel keeps unknown obligations and complete negative budget visible", () => {
  const lines = deliveryLines({ task: { task_label: "Controlled", recommendation: { effective_model: "fixture/premium" }, response: null, current_result: { desired_result: false } },
    delivery: { policy_model: "fixture/cheap", gateway_model: "company-cheap", provider_model: "fixture-provider-cheap", task_cap_usd: "0.10", known_cost_usd: "1.30",
      unknown_attempts: 1, attempt_reserved_usd: "0.04", remaining_task_usd: "-1.24" } })
  assert.ok(lines.some(x => x.includes("-1.24")))
  assert.ok(lines.some(x => x.includes("1.30")))
  assert.ok(lines.some(x => x.includes("Unknown obligations: 1")))
  assert.ok(lines.some(x => x.includes("Reported desired result: false")))
  assert.ok(lines.some(x => x.includes("not pilot approval")))
})

test("coordinator refuses duplicate explicit starts before another company request", async () => {
  let calls = 0
  const coordinator = new DeliveryCoordinator({ company: { async call() { calls++; throw new Error("Controlled outage") } }, session: {}, directory: "/synthetic/work",
    gatewayRef: "controlled-gateway", providerID: "company", gatewayOrigin: "https://gateway.company.example" })
  const input = { clientTaskID: "fixed-controlled-id" }
  await assert.rejects(coordinator.newTask(input), /outage/)
  await assert.rejects(coordinator.newTask(input), /already submitted/)
  assert.equal(calls, 1)
})

test("separate delivery entrypoint registers typed RPC and all request kinds with controlled host", async () => {
  const text = await readFile(new URL("../src/delivery-index.mjs", import.meta.url), "utf8")
  const hooks = [], implementations = []
  let disposals = 0
  const registration = { async dispose() { disposals++ } }
  const scope = { Plugin: { define: value => value }, credentialFile: async () => ({ origin: "https://policy.company.example", credential: "controlled" }),
    CompanyClient: class {}, DeliveryCoordinator: class { constructor() { return { connect() {}, newTask() {}, state() {}, feedback() {}, end() {}, request() {}, websocket() {}, prepareOptions() {} } } }, DeliveryRPC: {} }
  vm.runInNewContext(text.replace(/^import .*$/gm, "").replace("export default ", "globalThis.plugin = "), scope)
  const cleanup = await scope.plugin.setup({ options: { privateDeveloperService: true, credentialFile: "/synthetic/pairing" }, app: { version: "2.0.21" },
    location: { directory: "/synthetic/work" }, rpc: { async register(contract, implementation) { implementations.push(implementation); return registration } },
    session: { async hook(name) { hooks.push(name); return registration } } })
  assert.deepEqual(Object.keys(implementations[0]), ["connect", "start", "state", "feedback", "end"])
  assert.deepEqual(hooks, ["http.request", "experimental.ws.handshake", "context", "compaction", "title", "generate"])
  await cleanup()
  assert.equal(disposals, 7)
  const pkg = JSON.parse(await readFile(new URL("../delivery/package.json", import.meta.url), "utf8"))
  assert.equal(pkg.private, true)
  assert.equal(pkg.exports["./tui"], "./tui.tsx")
})

test("all outgoing kinds keep fixed model and explicit output cap without altering other work", () => {
  const adapter = new FreshSessionDeliveryAdapter({ company: {}, session: {}, gatewayRef: "controlled", providerID: "company",
    gatewayOrigin: "https://gateway.company.example", outputLimit: 1000 })
  adapter.binding = { model: { providerID: "company", id: "company-cheap" } }
  for (const kind of ["primary", "title", "compaction", "generate"]) {
    const event = { sessionID: adapter.sessionID, kind, model: adapter.binding.model, options: { maxTokens: 2000 } }
    adapter.prepareOptions(event)
    assert.equal(event.options.maxTokens, 1000)
  }
  const smaller = { sessionID: adapter.sessionID, model: adapter.binding.model, options: { maxTokens: 50 } }
  adapter.prepareOptions(smaller)
  assert.equal(smaller.options.maxTokens, 50)
  const unrelated = { sessionID: "ses_unrelated", options: { maxTokens: 5000 } }
  adapter.prepareOptions(unrelated)
  assert.equal(unrelated.options.maxTokens, 5000)
  assert.throws(() => adapter.prepareOptions({ sessionID: adapter.sessionID, model: { providerID: "company", id: "other" }, options: {} }), /model changed/)
  assert.throws(() => adapter.prepareOptions({ sessionID: adapter.sessionID, model: adapter.binding.model, options: { maxTokens: "unknown" } }), /invalid output/)
})

function quickSetup({ attempts = [{ outcome: "completed" }], unknown = 0, reserved = "0", known = "0.0017" } = {}) {
  const base = setup()
  const confirms = []
  base.config.quick_start = { selectedModel: "fixture/premium", requiredTools: ["read", "edit"], contextTokens: 20000, outputLimit: 4096, taskCapUSD: "0.10", labelPrefix: "junior" }
  base.config.scopes[0].routes[0].local_tools = [{ capability: "read" }, { capability: "edit" }]
  base.context.ui.dialog.confirm = async value => { confirms.push(value); return true }
  base.context.ui.dialog.select = async () => { throw new Error("quick start must not ask") }
  base.context.ui.dialog.prompt = async () => { throw new Error("quick start must not ask") }
  base.rpc.state = async input => { base.calls.push({ method: "state", input })
    return { task: { task_revision: 4, response: null, reported_actual_model: null },
      delivery: { policy_model: "fixture/cheap", unknown_attempts: unknown, attempt_reserved_usd: reserved, known_cost_usd: known, attempts } } }
  base.rpc.feedback = async input => { base.calls.push({ method: "feedback", input }) }
  return { ...base, confirms }
}

test("quick start asks once, uses reviewed defaults, and records the explicit acceptance", async () => {
  const { actions, calls, toasts, confirms } = quickSetup()
  await actions.quick()
  assert.equal(toasts.length, 0)
  assert.equal(confirms.length, 1)
  assert.equal(confirms[0].label.confirm, "Use suggestion")
  assert.deepEqual(calls.map(x => x.method), ["start", "navigate", "state", "feedback", "state"])
  const input = calls[0].input
  assert.equal(input.selectedModel, "fixture/premium")
  assert.equal(input.overrideModel, null)
  assert.equal(input.taskType, "documentation")
  assert.deepEqual(input.requiredTools, ["read", "edit"])
  assert.equal(input.taskCapUSD, "0.10")
  assert.match(input.taskLabel, /^junior-\d{8}-\d{6}$/)
  assert.deepEqual(calls[3].input, { sessionID: "ses_new_bound", action: "response", expectedRevision: 4, value: "accept" })
})

test("quick start: keep mine, missing defaults, or no usable scope start nothing", async () => {
  const kept = quickSetup()
  kept.context.ui.dialog.confirm = async () => false
  await kept.actions.quick()
  assert.equal(kept.calls.length, 0)
  const missing = quickSetup(); delete missing.config.quick_start
  await missing.actions.quick()
  assert.equal(missing.calls.length, 0)
  assert.equal(missing.toasts.length, 1)
  const invalid = quickSetup(); invalid.config.quick_start.selectedModel = "not/approved"
  await invalid.actions.quick()
  assert.equal(invalid.calls.length, 0)
  const stale = quickSetup(); stale.config.scopes[0].authority_current = false
  await stale.actions.quick()
  assert.equal(stale.calls.length, 0)
})

test("quick end reports the gateway-observed model only for a clean, known-cost run", async () => {
  const clean = quickSetup()
  await clean.actions.quick()
  clean.calls.length = 0
  clean.context.data.session.status = () => "idle"
  await clean.actions.end()
  assert.match(clean.confirms.at(-1).message, /report fixture\/cheap/)
  assert.deepEqual(clean.calls.filter(x => x.method === "feedback").map(x => x.input),
    [{ sessionID: "ses_new_bound", action: "actual_model", expectedRevision: 4, value: "fixture/cheap" }])
  for (const unsafe of [{ unknown: 1 }, { reserved: "0.01" }, { known: "0" }, { attempts: [] }, { attempts: [{ outcome: "completed" }, { outcome: "failed" }] }]) {
    const run = quickSetup(unsafe)
    await run.actions.quick()
    run.calls.length = 0
    run.context.data.session.status = () => "idle"
    await run.actions.end()
    assert.equal(run.calls.filter(x => x.method === "feedback").length, 0, JSON.stringify(unsafe))
    assert.equal(run.calls.filter(x => x.method === "end").length, 1)
  }
})

test("explicit start never reports a model at end", async () => {
  const explicit = quickSetup()
  explicit.context.data.session.status = () => "idle"
  explicit.changeRoute({ type: "session", sessionID: "ses_explicit" })
  await explicit.actions.end()
  assert.deepEqual(explicit.calls.map(x => x.method), ["end", "state"])
})

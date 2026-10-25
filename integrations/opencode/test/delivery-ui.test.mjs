import test from "node:test"
import assert from "node:assert/strict"
import { deliveryActions, deliveryLines, RATINGS, SUCCESS_RATING } from "../src/delivery-actions.mjs"
import { DeliveryCoordinator } from "../src/delivery-coordinator.mjs"
import { readFile } from "node:fs/promises"
import vm from "node:vm"
import { FreshSessionDeliveryAdapter } from "../src/delivery-adapter.mjs"

function setup(timing) {
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
  const actions = deliveryActions({ rpc, context, status: () => state, setStatus: value => { state = value }, timing })
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
  const { actions, context, calls, toasts, rpc } = setup()
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
  // A session that is not a Tarkado task refuses with a reason, before any confirmation.
  await actions.end()
  assert.deepEqual(calls.map(x => x.method), ["state"])
  assert.equal(toasts.length, 7)
  assert.match(toasts[6].message, /not a Tarkado task/)
  calls.length = 0
  rpc.state = async input => { calls.push({ method: "state", input }); return { task: { task_revision: 1 } } }
  await actions.end()
  assert.deepEqual(calls[1], { method: "end", input: { sessionID: "ses_unrelated_active" } })
  // Ended without a reported model: no rating is asked; the developer is told how to rate later.
  assert.equal(toasts.length, 8)
  assert.match(toasts[7].message, /report the model used/)
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

function quickSetup({ attempts = [{ outcome: "completed" }], unknown = 0, reserved = "0", known = "0.0017", suggested = "fixture/cheap", rating = "",
  costClosed = true, timing } = {}) {
  const base = setup(timing)
  const confirms = []
  base.config.quick_start = { selectedModel: "fixture/premium", requiredTools: ["read", "edit"], contextTokens: 20000, outputLimit: 4096, taskCapUSD: "0.10", labelPrefix: "junior" }
  base.config.scopes[0].routes[0].local_tools = [{ capability: "read" }, { capability: "edit" }]
  base.context.ui.dialog.confirm = async value => { confirms.push(value); return true }
  const selects = []
  // Quick start itself never asks; only End offers the optional rating.
  base.context.ui.dialog.select = async value => { selects.push(value); if (value.title.startsWith("Rate")) return rating; throw new Error("quick start must not ask") }
  base.context.ui.dialog.prompt = async () => { throw new Error("quick start must not ask") }
  let reported = null, closed = false, result = null
  base.rpc.end = async input => { base.calls.push({ method: "end", input }); closed = true }
  base.rpc.state = async input => { base.calls.push({ method: "state", input })
    if (input.sessionID === "ses_unrelated_active") return { task: null }
    return { task: { task_revision: 4, response: null, reported_actual_model: reported, closed, recommendation: { recommended_model: suggested }, current_result: result },
      delivery: { policy_model: "fixture/cheap", unknown_attempts: unknown, attempt_reserved_usd: reserved, known_cost_usd: known, attempts, closed: costClosed } } }
  base.rpc.feedback = async input => { base.calls.push({ method: "feedback", input })
    if (input.action === "actual_model") reported = input.value
    if (input.action === "result") result = { result_id: "res_1", ...input.value } }
  return { ...base, confirms, selects, report: value => { reported = value }, closeCost: () => { costClosed = true }, setResult: value => { result = value } }
}

test("quick start asks once, uses reviewed defaults, and records the explicit acceptance", async () => {
  const { actions, calls, toasts, confirms } = quickSetup()
  await actions.quick()
  assert.equal(toasts.length, 0)
  assert.equal(confirms.length, 1)
  assert.equal(confirms[0].label.confirm, "Use suggestion")
  assert.deepEqual(calls.map(x => x.method), ["state", "start", "navigate", "state", "feedback", "state"])
  const input = calls[1].input
  assert.equal(input.selectedModel, "fixture/premium")
  assert.equal(input.overrideModel, null)
  assert.equal(input.taskType, "documentation")
  assert.deepEqual(input.requiredTools, ["read", "edit"])
  assert.equal(input.taskCapUSD, "0.10")
  assert.match(input.taskLabel, /^junior-\d{8}-\d{6}$/)
  assert.deepEqual(calls[4].input, { sessionID: "ses_new_bound", action: "response", expectedRevision: 4, value: "accept" })
})

test("quick start never records acceptance of a suggestion that names another model", async () => {
  // A stale learner can suggest the developer's usual model while the approved trial routes another.
  const { actions, calls, toasts } = quickSetup({ suggested: "fixture/premium" })
  await actions.quick()
  assert.equal(toasts.length, 0)
  assert.equal(calls.filter(x => x.method === "start").length, 1)
  assert.equal(calls.filter(x => x.method === "feedback").length, 0)
})

test("quick start: keep mine, missing defaults, or no usable scope start nothing", async () => {
  const kept = quickSetup()
  kept.context.ui.dialog.confirm = async () => false
  await kept.actions.quick()
  assert.deepEqual(kept.calls.map(x => x.method), ["state"])
  const inside = quickSetup(); inside.changeRoute({ type: "session", sessionID: "ses_open_task" })
  await inside.actions.quick()
  assert.equal(inside.calls.filter(x => x.method === "start").length, 0)
  assert.match(inside.toasts[0].message, /already a Tarkado task/)
  const missing = quickSetup(); delete missing.config.quick_start
  await missing.actions.quick()
  assert.equal(missing.calls.filter(x => x.method !== "state").length, 0)
  assert.equal(missing.toasts.length, 1)
  const invalid = quickSetup(); invalid.config.quick_start.selectedModel = "not/approved"
  await invalid.actions.quick()
  assert.equal(invalid.calls.filter(x => x.method !== "state").length, 0)
  const stale = quickSetup(); stale.config.scopes[0].authority_current = false
  await stale.actions.quick()
  assert.equal(stale.calls.filter(x => x.method !== "state").length, 0)
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
    // Without a reported model the company cannot store a rating, so none is asked.
    assert.equal(run.selects.length, 0)
    assert.match(run.toasts.at(-1).message, /report the model used/)
  }
})

test("explicit start never reports a model at end", async () => {
  const explicit = quickSetup()
  explicit.context.data.session.status = () => "idle"
  explicit.changeRoute({ type: "session", sessionID: "ses_explicit" })
  await explicit.actions.end()
  assert.deepEqual(explicit.calls.map(x => x.method), ["state", "end", "state", "state"])
  assert.equal(explicit.calls.filter(x => x.method === "feedback").length, 0)
})

test("rate: only for an ended task whose model the developer reported", async () => {
  const later = quickSetup({ rating: "5" })
  later.changeRoute({ type: "session", sessionID: "ses_explicit" })
  await later.actions.rate()
  assert.match(later.toasts.at(-1).message, /End the task first/)
  later.context.data.session.status = () => "idle"
  await later.actions.end()
  assert.equal(later.selects.length, 0)
  later.report("fixture/cheap")
  later.calls.length = 0
  await later.actions.rate()
  await later.actions.ratingsSettled()
  const results = later.calls.filter(x => x.method === "feedback" && x.input.action === "result")
  assert.equal(results.length, 1)
  assert.equal(results[0].input.sessionID, "ses_explicit")
  assert.equal(results[0].input.value.score, "1")
  assert.equal(results[0].input.value.desired_result, true)
  // Rated once: a second rating would be a correction, which pauses the trial for review.
  await later.actions.rate()
  assert.match(later.toasts.at(-1).message, /already has a result/)
  assert.equal(later.calls.filter(x => x.method === "feedback" && x.input.action === "result").length, 1)
})

test("end offers an optional 0-5 rating and records it as the task's single result: 4-5 desired", async () => {
  const rated = quickSetup({ rating: "4" })
  await rated.actions.quick()
  rated.calls.length = 0
  rated.context.data.session.status = () => "idle"
  await rated.actions.end()
  await rated.actions.ratingsSettled()
  const ask = rated.selects.at(-1)
  assert.deepEqual(ask.options.map(x => x.value), ["5", "4", "3", "2", "1", "0", ""])
  assert.equal(ask.options.at(-1).title, "Skip")
  assert.equal(RATINGS.length, 6)
  const feedback = rated.calls.filter(x => x.method === "feedback").map(x => x.input)
  assert.equal(feedback[0].action, "actual_model")
  assert.deepEqual(feedback[1], { sessionID: "ses_new_bound", action: "result", expectedRevision: 4, value: {
    desired_result: true, tests_passed: null, score: "0.8", cost_usd: null, latency_ms: null, evidence_ref: "developer-rating-0-5", supersedes: null } })
  assert.equal(feedback.length, 2)
  assert.match(rated.toasts.at(-1).message, /Rating 4\/5 recorded/)
  assert.equal(SUCCESS_RATING, 4)
  for (const [value, score, desired] of [["5", "1", true], ["0", "0", false], ["3", "0.6", false]]) {
    const run = quickSetup({ rating: value })
    await run.actions.quick()
    run.context.data.session.status = () => "idle"
    await run.actions.end()
    await run.actions.ratingsSettled()
    const recorded = run.calls.filter(x => x.method === "feedback" && x.input.action === "result")
    assert.equal(recorded.length, 1)
    assert.equal(recorded[0].input.value.score, score)
    assert.equal(recorded[0].input.value.desired_result, desired)
  }
  for (const skipped of ["", undefined, "7", "controlled-scope"]) {
    const run = quickSetup({ rating: skipped })
    await run.actions.quick()
    run.context.data.session.status = () => "idle"
    await run.actions.end()
    await run.actions.ratingsSettled()
    assert.equal(run.calls.filter(x => x.method === "feedback" && x.input.action === "result").length, 0, String(skipped))
    assert.equal(run.calls.filter(x => x.method === "end").length, 1)
  }
})

test("a rating waits in the background for the cost record to close, then records once", async () => {
  const run = quickSetup({ rating: "5", costClosed: false, timing: { waitMs: 2000, pollMs: 5 } })
  await run.actions.quick()
  run.context.data.session.status = () => "idle"
  await run.actions.end()
  // End returned while the rating waits; nothing recorded while the cost record is open.
  assert.match(run.toasts.at(-1).message, /saved\. It is recorded once the company has this task's final cost/)
  assert.equal(run.calls.filter(x => x.method === "feedback" && x.input.action === "result").length, 0)
  await run.actions.rate()
  assert.match(run.toasts.at(-1).message, /already waiting/)
  run.closeCost()
  await run.actions.ratingsSettled()
  const recorded = run.calls.filter(x => x.method === "feedback" && x.input.action === "result")
  assert.equal(recorded.length, 1)
  assert.equal(recorded[0].input.value.desired_result, true)
  assert.match(run.toasts.at(-1).message, /Rating 5\/5 recorded/)
})

test("a rating is never recorded over an existing result, and gives up visibly if the record stays open", async () => {
  const open = quickSetup({ rating: "4", costClosed: false, timing: { waitMs: 30, pollMs: 5 } })
  await open.actions.quick()
  open.context.data.session.status = () => "idle"
  await open.actions.end()
  await open.actions.ratingsSettled()
  assert.equal(open.calls.filter(x => x.method === "feedback" && x.input.action === "result").length, 0)
  assert.match(open.toasts.at(-1).message, /not recorded yet: this task's final cost is still unknown/)
  const raced = quickSetup({ rating: "4", costClosed: false, timing: { waitMs: 2000, pollMs: 5 } })
  await raced.actions.quick()
  raced.context.data.session.status = () => "idle"
  await raced.actions.end()
  raced.setResult({ result_id: "res_other", desired_result: null })
  raced.closeCost()
  await raced.actions.ratingsSettled()
  assert.equal(raced.calls.filter(x => x.method === "feedback" && x.input.action === "result").length, 0)
  assert.match(raced.toasts.at(-1).message, /already had a result/)
})

test("task panel shows the developer rating out of 5", () => {
  const base = { task_label: "Controlled", recommendation: { effective_model: "fixture/premium" }, response: "accept" }
  assert.ok(deliveryLines({ task: { ...base, current_result: { desired_result: null, score: "0.8" } } }).includes("Developer rating: 4/5"))
  assert.ok(deliveryLines({ task: { ...base, current_result: null } }).includes("Developer rating: not rated"))
})

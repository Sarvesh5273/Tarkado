import test from "node:test"
import assert from "node:assert/strict"
import { Connector } from "../src/core.mjs"
import { fingerprint, origin, CompanyClient } from "../src/client.mjs"
import { taskLines } from "../src/actions.mjs"

function fixture() {
  const calls = []
  let fail = false
  const client = { async call(method, value) {
    calls.push({ method, value: structuredClone(value) })
    if (fail) throw new Error("Synthetic outage")
    if (method === "status") return { collection_fields: ["actual_model", "observation_kind", "request_kind", "http_status", "attempt", "retry", "coverage_status"], open_tasks: [] }
    if (method === "start") return { connector_task_ref: "00000000-0000-4000-8000-000000000001", session_ref: value.session_ref, sequence: 0,
      task_revision: 1, task_label: value.task_label, closed: false, recommendation: { effective_model: value.selected_model, recommended_model: "fixture/cheap", fallback_model: "fixture/premium", reason: "Synthetic rule", confidence: "low", policy_version: "synthetic-v1" },
      policy_current: true, observed_attempt_models: [], coverage_status: "incomplete", gap_count: 0 }
    if (method === "observation") return { ...connector.tasks.get(fingerprint("ses_synthetic")), sequence: value.sequence, closed: value.payload.observation_kind === "close" }
    return { ...connector.tasks.get(fingerprint("ses_synthetic")), task_revision: 2 }
  } }
  const connector = new Connector({ client, directory: "/synthetic/work", version: "2.0.21", session: { async get() { return { location: { directory: "/synthetic/work" } } } } })
  return { connector, calls, setFail(value) { fail = value } }
}
const input = { sessionID: "ses_synthetic", taskLabel: "Synthetic task", selectedModel: "fixture/premium", taskType: "documentation", riskTags: ["low"], requiredTools: ["read"], contextTokens: 2000 }

test("explicit start hashes references and preserves manual choice without prompt", async () => {
  const { connector, calls } = fixture()
  const state = await connector.start(input)
  assert.equal(state.recommendation.effective_model, "fixture/premium")
  const payload = calls.find(call => call.method === "start").value
  assert.equal(payload.session_ref, fingerprint("ses_synthetic"))
  assert.equal(payload.location_sha256, fingerprint("/synthetic/work"))
  assert.equal("sessionID" in payload, false)
  assert.equal("prompt" in payload, false)
})

test("capture fixed metadata without touching messages headers body or error text", async () => {
  const { connector, calls } = fixture()
  await connector.start(input)
  const event = { sessionID: "ses_synthetic", model: { providerID: "fixture", id: "cheap" }, kind: "primary" }
  for (const field of ["messages", "headers", "body", "prompt", "tools"]) Object.defineProperty(event, field, { get() { throw new Error("Forbidden field read") } })
  const before = structuredClone({ sessionID: event.sessionID, model: event.model, kind: event.kind })
  await connector.capture(event, "model_attempt")
  await connector.flush()
  const captured = calls.find(call => call.method === "observation").value.payload
  assert.equal(captured.model, "fixture/cheap")
  assert.deepEqual({ sessionID: event.sessionID, model: event.model, kind: event.kind }, before)
  assert.deepEqual(Object.keys(captured), ["observation_kind", "request_kind", "model", "http_status", "attempt", "retry", "coverage_status"])
})

test("delivery retries retain immutable event identity and no duplicate reservation", async () => {
  const f = fixture()
  await f.connector.start(input)
  f.setFail(true)
  await f.connector.capture({ sessionID: input.sessionID, model: { providerID: "fixture", id: "cheap" } }, "model_attempt")
  await f.connector.flush()
  assert.equal(f.connector.queue.length, 1)
  const event = structuredClone(f.connector.queue[0].body)
  f.setFail(false)
  await f.connector.flush()
  const attempts = f.calls.filter(call => call.method === "observation")
  assert.deepEqual(attempts.at(-1).value, event)
  assert.equal(f.connector.queue.length, 0)
})

test("unknown unregistered sessions ignored without enumerating private sessions", async () => {
  const { connector, calls } = fixture()
  await connector.capture({ sessionID: "ses_unrelated", model: { providerID: "fixture", id: "premium" } }, "model_attempt")
  assert.equal(calls.length, 0)
})

test("subagent and wrong location denied without startup", async () => {
  const { connector } = fixture()
  connector.session.get = async () => ({ parentID: "ses_parent", location: { directory: "/synthetic/work" } })
  await assert.rejects(connector.start(input), /root sessions/)
  connector.session.get = async () => ({ location: { directory: "/outside" } })
  await assert.rejects(connector.start(input), /root sessions/)
  assert.equal(connector.tasks.size, 0)
})

test("queue overflow retained as missing sequence instead of false completeness", async () => {
  const f = fixture()
  await f.connector.start(input)
  f.setFail(true)
  for (let i = 0; i < 260; i++) f.connector.enqueue(fingerprint(input.sessionID), { observation_kind: "gap", request_kind: "unknown", model: null, http_status: null, attempt: null, retry: null, coverage_status: "incomplete" })
  assert.equal(f.connector.queue.length, 256)
  assert.equal(f.connector.tasks.get(fingerprint(input.sessionID)).lost, 4)
  f.setFail(false)
  await f.connector.flush()
  f.connector.enqueue(fingerprint(input.sessionID), { observation_kind: "gap", request_kind: "unknown", model: null, http_status: null, attempt: null, retry: null, coverage_status: "incomplete" })
  assert.equal(f.connector.queue[0].body.sequence, 261)
})

test("no provider gateway or unsafe origin; redirects refused", async () => {
  for (const value of ["http://company.example", "https://company.example/path", "https://user:pass@company.example", "https://company.example?token=x"]) assert.throws(() => origin(value))
  assert.equal(origin("https://company.example"), "https://company.example")
  const requests = []
  const client = new CompanyClient({ origin: "http://127.0.0.1:8000", credential: "a".repeat(43) }, async (url, options) => { requests.push({ url, options }); return new Response("{}") })
  await client.call("status", {})
  assert.equal(requests[0].options.redirect, "error")
  assert.equal(requests[0].options.credentials, "omit")
  assert.match(requests[0].url, /api\/connectors\/v1\/status/)
  await assert.rejects(client.call("generate", {}), /Unsupported/)
})

test("panel distinguishes attempts gaps and confidence from verified success", () => {
  const state = { task: { task_label: "Synthetic task", recommendation: { effective_model: "premium", recommended_model: "cheap", fallback_model: "premium", reason: "rule", confidence: "low", policy_version: "v1" }, policy_current: false, observed_attempt_models: ["cheap", "standard"], coverage_status: "incomplete", gap_count: 2, multiple_models: true } }
  assert.match(taskLines(state).join("\n"), /not success probability/)
  assert.match(taskLines(state).join("\n"), /multiple models: true/)
  assert.match(taskLines(state).join("\n"), /historical/)
})

test("retry kind remains unknown and payload never contains provider error text", async () => {
  const { connector, calls } = fixture()
  await connector.start(input)
  await connector.capture({ sessionID: input.sessionID, kind: "unknown", model: { providerID: "fixture", id: "cheap" },
    attempt: 2, decision: { retry: true }, error: { message: "secret synthetic provider body" } }, "retry")
  await connector.flush()
  const payload = calls.find(call => call.method === "observation").value.payload
  assert.equal(payload.request_kind, "unknown")
  assert.equal(payload.attempt, 2)
  assert.equal(payload.retry, true)
  assert.equal("error" in payload, false)
})

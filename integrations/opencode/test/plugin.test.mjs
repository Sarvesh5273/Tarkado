import test from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile, chmod, symlink, rm, readFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import vm from "node:vm"
import { credentialFile } from "../src/client.mjs"
import { actions } from "../src/actions.mjs"
import { Connector } from "../src/core.mjs"

test("private credential input refuses symlinks/loose modes and never installs anything", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "tarkado-plugin-test-"))
  const file = path.join(directory, "credential.json")
  try {
    await writeFile(file, JSON.stringify({ origin: "http://127.0.0.1:8000", credential: "a".repeat(43) }), { mode: 0o600 })
    assert.equal((await credentialFile(file)).credential, "a".repeat(43))
    await chmod(file, 0o644)
    await assert.rejects(credentialFile(file), /owner-only/)
    await chmod(file, 0o600)
    await symlink(file, path.join(directory, "link.json"))
    await assert.rejects(credentialFile(path.join(directory, "link.json")), /owner-only/)
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test("server entrypoint registers only observation hooks and scoped RPC with controlled host", async () => {
  const text = await readFile(new URL("../src/index.mjs", import.meta.url), "utf8")
  const hooks = [], rpc = []
  const instance = { capture() {}, unload() {} }
  const context = {
    Plugin: { define: value => value }, credentialFile: async () => ({ origin: "http://127.0.0.1:8000", credential: "synthetic" }),
    CompanyClient: class {}, Connector: class { constructor() { return instance } }, Tarkado: {},
    setInterval: () => 1, clearInterval: () => {},
  }
  instance.connect = async () => ({})
  const script = text.replace(/^import .*$/gm, "").replace("export default ", "globalThis.plugin = ")
  vm.runInNewContext(script, context)
  const ctx = { options: { credentialFile: "/synthetic/credential", privateDeveloperService: true }, location: { directory: "/synthetic/work" }, app: { version: "2.0.21" },
    rpc: { async register(contract, implementation) { rpc.push(implementation) } }, session: { async hook(kind, fn) { hooks.push({ kind, fn }) } } }
  const cleanup = await context.plugin.setup(ctx)
  assert.deepEqual(hooks.map(h => h.kind), ["context", "compaction", "title", "generate", "http.response", "retry"])
  assert.deepEqual(Object.keys(rpc[0]), ["connect", "state", "start", "feedback", "close"])
  assert.equal(typeof cleanup, "function")
  cleanup()
  await assert.rejects(context.plugin.setup({ ...ctx, options: { credentialFile: "/synthetic/credential" } }), /private single-developer/)
  for (const denied of ["switchModel", "prompt(", "generate.text", "integration.connection", "session.context", "http.request", "ws.send", "ws.receive"]) assert.equal(text.includes(denied), false)
})

test("terminal feedback cannot follow a changed session after a dialog", async () => {
  let route = { type: "session", sessionID: "ses_one" }
  let sent = 0, shown = 0
  const current = { task_revision: 1, observed_attempt_models: ["fixture/cheap"] }
  let status = { task: current }
  const context = { location: { directory: "/synthetic/work" }, data: { session: { status: () => null } },
    ui: { router: { current: () => route }, dialog: { prompt: async () => { route = { type: "session", sessionID: "ses_two" }; return "fixture/cheap" } }, toast: { show() { shown++ } } } }
  const rpc = { async state() { return { task: current } }, async feedback() { sent++ } }
  const act = actions({ rpc, context, status: () => status, setStatus: value => { status = value } })
  await act.reportModel()
  assert.equal(sent, 0)
  assert.equal(shown, 1)
})

test("reload recovers open task with explicit gap but reconnect does not repeatedly add gaps", async () => {
  const state = { session_ref: "a".repeat(64), connector_task_ref: "b".repeat(36), sequence: 4, closed: false }
  const payloads = []
  const client = { async call(method, value) {
    if (method === "status") return { collection_fields: ["observation_kind", "request_kind", "coverage_status", "actual_model"], open_tasks: [state], recent_tasks: [state] }
    payloads.push(value)
    return { ...state, sequence: value.sequence }
  } }
  const connector = new Connector({ client, directory: "/synthetic/work", session: {}, version: "2.0.21" })
  await connector.connect()
  assert.equal(payloads.length, 1)
  assert.equal(payloads[0].payload.observation_kind, "gap")
  assert.equal(payloads[0].sequence, 5)
  await connector.connect()
  assert.equal(payloads.length, 1)
})

test("late capture cannot move into a newly started task while awaiting host metadata", async () => {
  let release
  const wait = new Promise(resolve => { release = resolve })
  const calls = []
  const client = { async call(method, body) { calls.push({ method, body }); return {} } }
  const connector = new Connector({ client, directory: "/synthetic/work", version: "2.0.21", session: { get: async () => { await wait; return { location: { directory: "/synthetic/work" } } } } })
  const { fingerprint } = await import("../src/client.mjs")
  const key = fingerprint("ses_one")
  connector.tasks.set(key, { connector_task_ref: "old", sequence: 0 })
  const captured = connector.capture({ sessionID: "ses_one", model: { providerID: "fixture", id: "cheap" } }, "model_attempt")
  await assert.rejects(connector.newTask({ sessionID: "ses_one" }), /pending metadata/)
  connector.tasks.set(key, { connector_task_ref: "new", sequence: 0 })
  release()
  await captured
  assert.equal(calls.length, 0)
  assert.equal(connector.queue.length, 0)
  assert.match(connector.problem, /Late observation/)
})

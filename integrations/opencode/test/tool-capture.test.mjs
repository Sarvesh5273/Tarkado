import test from "node:test"
import assert from "node:assert/strict"
import { ToolCapture } from "../src/tool-capture.mjs"
import { DeliveryCoordinator } from "../src/delivery-coordinator.mjs"
import { readFile } from "node:fs/promises"
import vm from "node:vm"

function setup({ key = true, limit = 256 } = {}) {
  const sent = [], adapter = { sessionID: "ses_exact", sessionHash: "a".repeat(64), descriptor: { connectorTaskRef: "exact-task" },
    binding: { task_token: "synthetic-private-task-token", local_tools: [{ name: "read", capability: "read", function_sha256: "b".repeat(64) },
      { name: "run_tests", capability: "test", function_sha256: "c".repeat(64), ...(key ? { status_metadata_key: "tarkado_status_v1" } : {}) }] } }
  const company = { async call(method, data) { assert.equal(method, "tool-status"); sent.push(structuredClone(data)); return {} } }
  const capture = new ToolCapture({ company, adapter, location: "d".repeat(64), clock: () => "2026-10-04T12:00:00Z", limit })
  const event = { sessionID: "ses_exact", messageID: "msg_synthetic_exact", id: "call_synthetic_exact", tool: "run_tests" }
  return { sent, adapter, company, capture, event }
}

test("native execution error projects exact identity/status without reading inputs or error text", async () => {
  const { capture, event, sent, adapter } = setup({ key: false })
  Object.defineProperty(event, "input", { get() { throw new Error("No arguments may be read") } })
  capture.before(event)
  const after = { ...event, status: "error", error: {} }
  Object.defineProperty(after.error, "message", { get() { throw new Error("No error text may be read") } })
  capture.after(after)
  await capture.flush()
  assert.equal(sent.length, 2)
  assert.equal(sent[1].payload.tool_status, "execution_error")
  assert.equal(sent[0].payload.tool_invocation_ref, sent[1].payload.tool_invocation_ref)
  assert.equal(sent[1].payload.tool_attempt_ref, null)
  const json = JSON.stringify(sent)
  for (const secret of [adapter.binding.task_token, event.messageID, event.id]) assert.equal(json.includes(secret), false)
})

test("structured intermediate test failure permission refusal and interruption use reviewed metadata only", async () => {
  for (const status of ["test_failed", "permission_refused", "interrupted"]) {
    const { capture, event, sent } = setup()
    capture.before(event)
    const result = { metadata: { tarkado_status_v1: { schema_version: 1, status } } }
    for (const key of ["output", "content"]) Object.defineProperty(result, key, { get() { throw new Error("No outputs may be read") } })
    capture.after({ ...event, status: "completed", result })
    await capture.flush()
    assert.equal(sent.at(-1).payload.tool_status, status)
    assert.equal(sent.at(-1).payload.tool_status_source, "reviewed_tool_metadata")
  }
})

test("completed arbitrary output is not tests passed and unreviewed metadata is ignored", async () => {
  const { capture, event, sent } = setup({ key: false })
  capture.before(event)
  capture.after({ ...event, status: "completed", result: { content: "FAILED 10 tests permission denied cancelled", metadata: { tests_passed: false,
    tarkado_status_v1: { schema_version: 1, status: "test_failed" } } } })
  await capture.flush()
  assert.equal(sent.at(-1).payload.tool_status, "completed")
  assert.equal(Object.hasOwn(sent.at(-1).payload, "tests_passed"), false)
  assert.equal(JSON.stringify(sent).includes("FAILED 10 tests"), false)
})

test("missing result or absent after hook stays unknown and late result retains a distinct event", async () => {
  const { capture, event, sent } = setup()
  capture.before(event)
  await capture.barrier()
  assert.equal(sent.at(-1).payload.tool_status, "unknown")
  assert.equal(sent.at(-1).payload.tool_status_source, "missing_after_hook")
  capture.after({ ...event, status: "completed", result: {} })
  await capture.flush()
  assert.deepEqual(sent.map(item => item.payload.tool_status), ["started", "unknown", "completed"])
  assert.deepEqual(sent.map(item => item.sequence), [1, 2, 3])
  assert.equal(new Set(sent.map(item => item.event_id)).size, 3)
  const other = setup(); other.capture.before(other.event); other.capture.after({ ...other.event, status: "completed" }); await other.capture.flush()
  assert.equal(other.sent.at(-1).payload.tool_status, "unknown")
})

test("hook duplicates are idempotent and immutable network retries keep original event identity", async () => {
  const { capture, event, company, sent } = setup()
  let first, attempts = 0
  company.call = async (method, value) => { attempts++; if (!first) { first = structuredClone(value); throw new Error("Synthetic disconnect") }; sent.push(structuredClone(value)) }
  capture.before(event); await capture.flush()
  capture.before(event)
  await capture.flush()
  assert.deepEqual(sent[0], first)
  capture.after({ ...event, status: "error", error: {} }); await capture.flush()
  capture.after({ ...event, status: "error", error: {} }); await capture.flush()
  assert.equal(sent.length, 2)
  assert.equal(attempts, 3)
})

test("wrong session is untouched and orphan/unapproved identity retains a gap not guessed completion", async () => {
  const { capture, event, sent } = setup()
  capture.before({ ...event, sessionID: "ses_unrelated" }); await capture.flush()
  assert.equal(sent.length, 0)
  capture.after({ ...event, status: "error", error: {} }); await capture.flush()
  assert.equal(sent[0].payload.tool_status, "gap")
  assert.equal(sent[0].payload.tool_invocation_ref, null)
  capture.before({ ...event, tool: "shell" }); await capture.flush()
  assert.equal(sent.at(-1).payload.tool_status, "gap")
})

test("queue overflow creates sequence holes and continuation refuses undelivered observations", async () => {
  const { capture, event, sent, company } = setup({ limit: 1 })
  let release
  company.call = async (method, value) => { sent.push(structuredClone(value)); await new Promise(resolve => { release = resolve }) }
  capture.before(event)
  capture.after({ ...event, status: "error", error: {} })
  assert.equal(capture.lost, 1)
  company.call = async (method, value) => { sent.push(structuredClone(value)); return {} }
  release()
  await capture.flush()
  assert.deepEqual(sent.map(item => item.sequence), [1, 3])
  assert.equal(sent.at(-1).payload.tool_status, "gap")
  const failed = setup(); failed.company.call = async () => { throw new Error("Synthetic outage") }
  failed.capture.before(failed.event)
  await assert.rejects(failed.capture.barrier(), /unavailable/)
  assert.equal(failed.capture.queue.length, 2)
})

test("restart uses scoped company metadata to append one gap without restoring session or tokens", async () => {
  const calls = []
  const coordinator = new DeliveryCoordinator({ company: { async call(method, value) { calls.push({ method, value }); return method === "delivery-options"
    ? { tool_capture_approved: true, tool_capture_tasks: [{ connector_task_ref: "exact-task", session_ref: "a".repeat(64), sequence: 5 }] } : {} } },
    session: {}, directory: "/synthetic", gatewayRef: "gateway", providerID: "company", gatewayOrigin: "https://gateway.company.example", toolFailureCapture: true })
  await coordinator.connect(); await coordinator.connect()
  const gaps = calls.filter(item => item.method === "tool-status")
  assert.equal(gaps.length, 1)
  assert.equal(gaps[0].value.sequence, 6)
  assert.equal(gaps[0].value.payload.tool_status, "gap")
  assert.equal(coordinator.adapters.size, 0)
})

test("capture initialization is persisted and source registration is explicitly opt-in", async () => {
  const { capture, sent } = setup(); await capture.open()
  assert.equal(sent[0].payload.tool_status, "capture_open")
  assert.equal(sent[0].payload.tool_invocation_ref, null)
  const text = await readFile(new URL("../src/delivery-index.mjs", import.meta.url), "utf8")
  const registered = [], disposed = []
  const registration = name => ({ async dispose() { disposed.push(name) } })
  const environment = { Plugin: { define: value => value }, credentialFile: async () => ({}), CompanyClient: class {}, DeliveryRPC: {},
    DeliveryCoordinator: class { captureUnload() { disposed.push("capture-cleanup") } }, }
  vm.runInNewContext(text.replace(/^import .*$/gm, "").replace("export default ", "globalThis.plugin = "), environment)
  const context = { app: { version: "2.0.21" }, options: { privateDeveloperService: true, toolFailureCapture: true }, location: { directory: "/synthetic" },
    rpc: { async register() { return registration("rpc") } }, session: { async hook(name) { return registration(name) } },
    tool: { async hook(name) { registered.push(name); return registration(name) } } }
  const cleanup = await environment.plugin.setup(context)
  assert.deepEqual(registered, ["execute.before", "execute.after"])
  await cleanup()
  assert.ok(disposed.includes("capture-cleanup"))
})

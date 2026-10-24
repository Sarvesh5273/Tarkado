// DEMO-ONLY driver: the full-loop runner's stand-in for a developer at the
// OpenCode UI. It talks to one developer's private `opencode serve` instance.
// Shadow tasks use the developer's normally chosen (unmanaged) gateway alias;
// routed tasks go only through the reviewed Tarkado delivery RPC, which creates
// the bound session. Output is metadata only: no prompt or completion text.
//
// Usage: node opencode_driver.mjs '<json command>'   (password via OC_PASSWORD)
import { OpenCode } from "@opencode/client"
import { DeliveryRPC } from "../../integrations/opencode/src/delivery-rpc.mjs"

const command = JSON.parse(process.argv[2])
const auth = "Basic " + Buffer.from("opencode:" + process.env.OC_PASSWORD).toString("base64")
const client = OpenCode.make({ baseUrl: command.url, headers: { authorization: auth } })
const location = { directory: command.directory }
const options = { location }

function usageOf(messages) {
  const total = { input: 0, output: 0, reasoning: 0, cache_read: 0, cache_write: 0 }
  const summary = { steps: 0, models: [], finishes: [], errors: [] }
  const user = messages.find(message => message.type === "user")
  const idle = [...messages].reverse().find(message => message.type === "idle")
  summary.complete = Boolean(user && idle && idle.time.created >= user.time.created)
  summary.latency_ms = summary.complete ? idle.time.created - user.time.created : null
  for (const message of messages) {
    if (message.type !== "assistant") continue
    summary.steps += 1
    const model = message.model ? `${message.model.providerID}/${message.model.id}` : null
    if (model && !summary.models.includes(model)) summary.models.push(model)
    if (message.finish) summary.finishes.push(message.finish)
    if (message.error) summary.errors.push(String(message.error.type ?? message.error.name ?? "error"))
    const tokens = message.tokens
    if (!tokens) { summary.unknown_usage = true; continue }
    total.input += tokens.input ?? 0
    total.output += tokens.output ?? 0
    total.reasoning += tokens.reasoning ?? 0
    total.cache_read += tokens.cache?.read ?? 0
    total.cache_write += tokens.cache?.write ?? 0
  }
  return { usage: total, ...summary }
}

async function messages(sessionID) {
  const result = await client.session.context({ sessionID }, options)
  return Array.isArray(result) ? result : result?.data ?? []
}

// session.wait() does not resolve once the run is already idle in 2.0.21, so
// poll the session context for the idle marker that follows the prompt.
async function runPrompt(sessionID, text, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let failure = null
  try {
    await client.session.prompt({ sessionID, text }, options)
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      if (usageOf(await messages(sessionID)).complete) break
      if (Date.now() > deadline) throw new Error("timed out waiting for the session to become idle")
    }
  } catch (error) {
    failure = String(error?.message ?? error).slice(0, 300)
  }
  const result = usageOf(await messages(sessionID))
  const info = await client.session.get({ sessionID }, options).catch(() => null)
  return { sessionID, failure, outcome: info?.outcome ?? null, session_usage: sessionUsage(info), ...result }
}

// Session totals include OpenCode's own title-generation call, which is billed
// too but is not one of the session's messages.
function sessionUsage(info) {
  const tokens = info?.tokens
  if (!tokens) return null
  return { input: tokens.input ?? 0, output: tokens.output ?? 0, reasoning: tokens.reasoning ?? 0,
           cache_read: tokens.cache?.read ?? 0, cache_write: tokens.cache?.write ?? 0 }
}

async function main() {
  const rpc = () => client.rpc(DeliveryRPC)
  switch (command.op) {
    case "shadow": {
      const session = await client.session.create({ model: { providerID: "company", id: command.model }, location }, options)
      return runPrompt(session.id, command.text, command.timeoutMs ?? 900000)
    }
    case "connect":
      return rpc().connect({}, options)
    // A routed task: `start` creates the bound session (no prompt); the developer
    // responds to the selection, then `prompt` submits the task text.
    case "start":
      return rpc().start(command.start, options)
    case "prompt":
      return runPrompt(command.sessionID, command.text, command.timeoutMs ?? 900000)
    case "state":
      return rpc().state({ sessionID: command.sessionID }, options)
    case "feedback":
      return rpc().feedback(command.feedback, options)
    case "end":
      return rpc().end({ sessionID: command.sessionID }, options)
    case "usage": {
      const info = await client.session.get({ sessionID: command.sessionID }, options)
      return { outcome: info.outcome ?? null, session_usage: sessionUsage(info), ...usageOf(await messages(command.sessionID)) }
    }
    default:
      throw new Error("unknown driver op")
  }
}

main().then(
  value => { process.stdout.write(JSON.stringify({ ok: true, value }) + "\n") },
  error => {
    // RPC failures carry the plugin's (metadata-only) message in their cause/data.
    const detail = [error?.message, error?.cause?.message ?? error?.cause, error?.data && JSON.stringify(error.data),
      error && JSON.stringify(Object.fromEntries(Object.entries(error)))].filter(Boolean).join(" | ")
    process.stdout.write(JSON.stringify({ ok: false, error: String(detail || error).slice(0, 2000) }) + "\n"); process.exitCode = 1
  },
)

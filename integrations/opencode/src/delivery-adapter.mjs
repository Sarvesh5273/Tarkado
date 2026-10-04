// Explicit fresh-session delivery source. Not registered by the observer plugin.
// No prompt, switchModel, private-session read, provider call, or disk spool.
import { createHash, createHmac, randomUUID } from "node:crypto"

const hash = value => createHash("sha256").update(value).digest("hex")
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object"
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value
const exact = (left, right) => JSON.stringify(canonical(left)) === JSON.stringify(canonical(right))

export class FreshSessionDeliveryAdapter {
  constructor({ company, session, gatewayRef, providerID, gatewayOrigin, outputLimit }) {
    this.company = company
    this.session = session
    this.descriptor = null
    this.gatewayRef = gatewayRef
    this.providerID = providerID
    if (outputLimit !== undefined && (!Number.isSafeInteger(outputLimit) || outputLimit < 1)) throw new Error("Explicit positive output limit is required.")
    this.outputLimit = outputLimit
    const origin = new URL(gatewayOrigin)
    if (origin.protocol !== "https:" || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== "/") {
      throw new Error("Delivery needs the exact operator-approved company gateway HTTPS origin.")
    }
    this.gatewayOrigin = origin.origin
    this.sessionID = `ses_${randomUUID().replaceAll("-", "")}`
    this.sessionHash = hash(this.sessionID)
    this.binding = null
    this.consumed = false
  }

  pendingSessionReference() { return this.sessionHash }

  setDescriptor({ request, scopeRef, connectorTaskRef, locationHash, sessionRef }) {
    if (this.descriptor || this.consumed || sessionRef !== this.sessionHash) throw new Error("New descriptor cannot reuse an existing task/session.")
    this.descriptor = structuredClone({ request, scopeRef, connectorTaskRef, locationHash })
  }

  async inspect(request) {
    if (!this.descriptor || this.consumed || !exact(request, this.descriptor.request) || request.boundary !== "new_task") {
      throw new Error("Only this unused explicit new-task descriptor can be bound; no active task switching.")
    }
    // The source cannot assert host/billing guarantees for itself. Independent
    // company-owned verification is read-only here and defaults to refusal.
    return this.company.call("delivery-preflight", { scope_ref: this.descriptor.scopeRef,
      connector_task_ref: this.descriptor.connectorTaskRef, location_sha256: this.descriptor.locationHash,
      selection_request: request, gateway_ref: this.gatewayRef })
  }

  async bind(boundary, choice) {
    if (!this.descriptor || this.consumed || boundary.requestID !== this.descriptor.request.selection_id || choice.selectionID !== boundary.requestID) {
      throw new Error("Descriptor is consumed or selection changed; no duplicate session delivery.")
    }
    this.consumed = true
    const binding = await this.company.call("delivery-bind", {
      scope_ref: this.descriptor.scopeRef,
      selection_id: choice.selectionID,
      connector_task_ref: this.descriptor.connectorTaskRef,
      location_sha256: this.descriptor.locationHash,
      gateway_ref: this.gatewayRef,
    })
    if (binding.model !== choice.model || binding.task_cap_usd !== choice.maxCostUSD || binding.session_ref !== this.sessionHash) {
      throw new Error("Server delivery binding differs from the exact task/model/budget/session.")
    }
    const model = { providerID: this.providerID, id: binding.gateway_model }
    // Creation binds a model on a NEW isolated session. There is no get/switch
    // of another active session, and no user prompt is submitted here.
    const created = await this.session.create({ id: this.sessionID, model })
    if (created.id !== this.sessionID || created.parentID || created.fork || !exact(created.model, model)) {
      throw new Error("Host did not create the exact fresh root/model; keep the claim spent and require recovery.")
    }
    this.binding = Object.freeze({ ...binding, model: Object.freeze(model) })
    return { sessionID: this.sessionID, executionSent: false }
  }

  async request(event) {
    if (event.sessionID !== this.sessionID) return
    if (!this.binding || !exact(event.model, this.binding.model)) throw new Error("Unbound or wrong-model task request refused.")
    if (!["primary", "title", "compaction", "generate"].includes(event.kind)) throw new Error("Unknown request kind refused.")
    const url = new URL(event.request.url)
    if (url.origin !== this.gatewayOrigin || url.pathname !== "/v1/chat/completions" || url.search || url.hash || event.request.method !== "POST") {
      throw new Error("Only the exact company LiteLLM text-chat endpoint is supported.")
    }
    // This new task's authorized inference payload is transient only. Tarkado
    // receives no body, prompt, output, or content hash. The gateway validates
    // the final physical request and refuses unsupported tools/billing options.
    const body = await event.request.clone().json()
    if (body.model !== this.binding.gateway_model) throw new Error("Wire model differs from fixed task model.")
    if (body.metadata) throw new Error("Unreviewed metadata overlay refused.")
    const functions = new Set((this.binding.local_tools ?? []).map(tool => tool.name))
    if (body.tools && (!Array.isArray(body.tools) || body.tools.some(tool => tool.type !== "function" || !functions.has(tool.function?.name)))) {
      throw new Error("Only this task's reviewed local function tools may be sent; remote/paid/hosted tools are refused.")
    }
    if (body.max_tokens !== undefined) {
      if (body.max_completion_tokens !== undefined) throw new Error("Conflicting output caps refused.")
      body.max_completion_tokens = body.max_tokens
      delete body.max_tokens
    }
    if (body.max_completion_tokens === undefined) throw new Error("An explicit reviewed output bound is required.")
    if (this.outputLimit !== undefined && body.max_completion_tokens > this.outputLimit) throw new Error("Wire output cap exceeds the explicitly confirmed task limit.")
    if (body.stream === true) {
      if (body.stream_options && Object.keys(body.stream_options).some(key => key !== "include_usage")) throw new Error("Unknown streaming options refused.")
      body.stream_options = { include_usage: true }
    }
    // Exact retry payloads keep the same opaque request ID, so a lost response
    // cannot duplicate paid delivery. Identical intentional re-execution is
    // conservatively unsupported in this first contract.
    const digest = createHmac("sha256", this.binding.task_token).update(JSON.stringify(canonical({ kind: event.kind, body }))).digest("hex")
    const requestID = `${digest.slice(0, 8)}-${digest.slice(8, 12)}-${digest.slice(12, 16)}-${digest.slice(16, 20)}-${digest.slice(20, 32)}`
    body.metadata = { tarkado_binding: this.binding.binding_ref, tarkado_task: this.binding.task_token,
      tarkado_session: this.sessionHash, tarkado_request: requestID, tarkado_kind: event.kind }
    const headers = new Headers(event.request.headers)
    headers.delete("content-length")
    event.request = new Request(event.request, { headers, body: JSON.stringify(body) })
  }

  websocket(event) {
    if (event.sessionID === this.sessionID) throw new Error("WebSocket delivery has no supported billing/attempt contract.")
  }

  prepareOptions(event) {
    if (event.sessionID !== this.sessionID) return
    if (!this.binding || !exact(event.model, this.binding.model)) throw new Error("Fixed task model changed; no continuation or auxiliary model switching.")
    if (this.outputLimit === undefined) throw new Error("This task has no explicit outgoing output limit.")
    if (event.options.maxTokens !== undefined && (!Number.isSafeInteger(event.options.maxTokens) || event.options.maxTokens < 1)) throw new Error("Unknown/invalid output override refused.")
    event.options.maxTokens = Math.min(event.options.maxTokens ?? this.outputLimit, this.outputLimit)
    if (event.tools) {
      // Remove only tools from THIS task's outgoing request, never the host tool
      // registry or another session. The gateway validates exact final schemas.
      // Local execution/permissions/no-paid-side-effects still require the
      // independent host verifier; a tool name/hash is not those guarantees.
      const allowed = new Set((this.binding.local_tools ?? []).map(tool => tool.name))
      for (const name of Object.keys(event.tools)) if (!allowed.has(name)) delete event.tools[name]
    }
  }
}

export async function registerDeliveryHooks(ctx, adapter) {
  // Explicit caller approval is needed to load/register this inactive source.
  const registrations = []
  registrations.push(await ctx.session.hook("http.request", event => adapter.request(event)))
  registrations.push(await ctx.session.hook("experimental.ws.handshake", event => adapter.websocket(event)))
  return async () => { for (const registration of registrations) await registration.dispose() }
}

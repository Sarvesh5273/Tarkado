import { randomUUID } from "node:crypto"
import { actions as feedbackActions, plainLocation } from "./actions.mjs"

export function deliveryLines(state) {
  const task = state?.task
  if (!task) return ["No bound delivery task in this source instance. Use /tarkado-delivery-start for a NEW isolated root.",
    "No prompt is submitted by these commands. Restarted/interrupted records remain in the company browser.", ...(state?.problem ? [state.problem] : [])]
  const delivery = state.delivery
  return [
    `Task: ${task.task_label} — ${task.closed ? "explicitly ended" : "open"}`,
    `Original manual choice: ${task.recommendation.effective_model ?? "Unknown"}`,
    `Bound policy model: ${delivery?.policy_model ?? "Unknown / not bound"}`,
    `Gateway / provider: ${delivery?.gateway_model ?? "Unknown"} / ${delivery?.provider_model ?? "Unknown"}`,
    `Task cap USD: ${delivery?.task_cap_usd ?? "Unknown"}`,
    `Known accounted cost USD: ${delivery?.known_cost_usd ?? "Unknown"}`,
    `Unknown obligations: ${delivery?.unknown_attempts ?? "Unknown"}; attempt reservations USD: ${delivery?.attempt_reserved_usd ?? "Unknown"}`,
    `Remaining task USD: ${delivery?.remaining_task_usd ?? "Unknown"}`,
    `One-task response: ${task.response ?? "Unknown"}; reported actual model: ${task.reported_actual_model ?? "Unknown"}`,
    `Reported desired result: ${task.current_result?.desired_result ?? "Unknown"}`,
    ...(delivery?.tool_capture ? [`Tool status signals: ${delivery.tool_capture.negative_signals.join(", ") || "none observed"}; pending invocations ${delivery.tool_capture.pending_invocations}; gaps ${delivery.tool_capture.gap_count}`,
      "Tool completion does not prove tests passed. Intermediate test failures are not final task outcomes."] : []),
    "Gateway accounting is not verified billing or engineering success. Human acceptance is not pilot approval.",
    ...(state.problem ? [state.problem] : []),
  ]
}

export function deliveryActions({ rpc, context, status, setStatus }) {
  const feedback = feedbackActions({ rpc, context, status, setStatus })
  let busy = false
  // Plain JSON copy: in the real OpenCode TUI the route/location are reactive store
  // proxies, which structuredClone refuses (DataCloneError), refusing every start.
  const snapshot = () => JSON.parse(JSON.stringify({ route: context.ui.router.current(), location: context.location }))
  const sameContext = original => {
    const current = snapshot()
    if (JSON.stringify(current) !== JSON.stringify(original)) throw new Error("Route/location changed; review a fresh explicit task.")
  }
  const run = operation => async () => {
    if (busy) return
    busy = true
    try { await operation() }
    catch { context.ui.toast.show({ title: "Tarkado delivery", message: "Delivery action refused/unavailable. Inspect company scope, verifier setup, pairing and retained accounting. Do not repeat a lost task start; use browser recovery.", variant: "error" }) }
    finally { busy = false }
  }
  // Sessions started through `quick`: only these get the gateway-observed model report at end.
  const quickSessions = new Set()
  const supported = configuration => configuration.source_kind === "team" && configuration.collection_supported
    && configuration.gateways?.some(row => row.gateway_ref === configuration.gateway_ref)
  const usable = configuration => configuration.scopes.filter(row => row.status === "active" && row.authority_current && row.routes.length
    && row.accounting.remaining_task_slots > 0)
  return {
    refresh: feedback.refresh,
    accept: feedback.accept, reject: feedback.reject, reportModel: feedback.reportModel, result: feedback.result, browser: feedback.browser,
    // One-confirmation start. Every bound comes from approver-reviewed defaults shipped with
    // the pairing (quick_start); the confirmation states them and is the developer's explicit
    // acceptance. Anything ambiguous (several scopes or categories) asks; anything missing refuses.
    quick: run(async () => {
      const original = snapshot()
      const configuration = await rpc.connect({}, { location: original.location })
      if (!supported(configuration)) throw new Error("No supported paired gateway/collection setup.")
      const defaults = configuration.quick_start
      if (!defaults) throw new Error("No reviewed quick-start defaults are configured; use /tarkado-delivery-start.")
      const scopes = usable(configuration)
      if (!scopes.length) throw new Error("No separately approved/verified scope is available.")
      let scope = scopes[0]
      if (scopes.length > 1) {
        const scopeRef = await context.ui.dialog.select({ title: "Which approved trial?", options: scopes.map(row => ({
          title: `${row.pilot_id} · remaining USD ${row.accounting.remaining_usd}`, value: row.scope_ref })) })
        if (scopeRef === undefined) return
        scope = scopes.find(row => row.scope_ref === scopeRef)
      }
      let route = scope.routes[0]
      if (scope.routes.length > 1) {
        const taskType = await context.ui.dialog.select({ title: "What kind of task is this?", options: scope.routes.map(row => ({ title: `${row.task_type} → ${row.model}`, value: row.task_type })) })
        if (taskType === undefined) return
        route = scope.routes.find(row => row.task_type === taskType)
      }
      const capabilities = new Set((route.local_tools ?? []).map(tool => tool.capability))
      const requiredTools = (defaults.requiredTools ?? []).filter(value => capabilities.has(value))
      const contextTokens = defaults.contextTokens, outputLimit = defaults.outputLimit, capText = String(defaults.taskCapUSD ?? "")
      if (!Number.isSafeInteger(contextTokens) || contextTokens < 1 || !Number.isSafeInteger(outputLimit) || outputLimit < 1
        || !/^\d+(\.\d+)?$/.test(capText) || !/[1-9]/.test(capText) || !configuration.models.includes(defaults.selectedModel)
        || !/^[A-Za-z0-9_-]{1,24}$/.test(defaults.labelPrefix ?? "")) throw new Error("Quick-start defaults are incomplete or invalid.")
      const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15)
      const taskLabel = `${defaults.labelPrefix}-${stamp}`
      const accepted = await context.ui.dialog.confirm({ title: "Tarkado suggestion", message:
        `This ${route.task_type} task can use ${route.model} instead of your usual ${defaults.selectedModel}.\n`
        + `Approved trial: ${scope.pilot_id} (USD ${scope.accounting.remaining_usd} left). This task: at most USD ${capText}.\n`
        + `Opens a new session for it; your current work and model stay unchanged.`,
        label: { confirm: "Use suggestion", cancel: "Keep mine" } })
      if (!accepted) return
      sameContext(original)
      const result = await rpc.start({ scopeRef: scope.scope_ref, repositoryRef: configuration.repository_ref, taskLabel, taskType: route.task_type, riskTags: ["low"],
        selectedModel: defaults.selectedModel, overrideModel: null, contextTokens, outputLimit, taskCapUSD: capText, clientTaskID: randomUUID(), requiredTools }, { location: original.location })
      if (!result.sessionCreated || result.executionSent !== false) throw new Error("No exact newly created bound session was returned.")
      sameContext(original)
      context.ui.router.navigate({ type: "session", sessionID: result.sessionID })
      quickSessions.add(result.sessionID)
      // "Use suggestion" was the explicit acceptance; record it for this task only.
      try {
        const current = await rpc.state({ sessionID: result.sessionID }, { location: original.location })
        if (current.task && current.task.response == null) await rpc.feedback({ sessionID: result.sessionID, action: "response",
          expectedRevision: current.task.task_revision, value: "accept" }, { location: original.location })
      } catch { context.ui.toast.show({ title: "Tarkado delivery", message: "Session started, but the acceptance was not recorded. Use /tarkado-delivery-accept.", variant: "warning" }) }
      await feedback.refresh()
    }),
    connect: run(async () => {
      const configuration = await rpc.connect({}, { location: plainLocation(context) })
      context.ui.toast.show({ title: "Tarkado delivery", message: `${configuration.scopes?.length ?? 0} paired scope records. This is not permission to execute; independent verification is rechecked.`, variant: "info" })
      await feedback.refresh()
    }),
    start: run(async () => {
      const original = snapshot()
      const configuration = await rpc.connect({}, { location: original.location })
      if (configuration.source_kind !== "team" || !configuration.collection_supported
        || !configuration.gateways?.some(row => row.gateway_ref === configuration.gateway_ref)) throw new Error("No supported paired gateway/collection setup.")
      const scopes = configuration.scopes.filter(row => row.status === "active" && row.authority_current && row.routes.length
        && row.accounting.remaining_task_slots > 0)
      if (!scopes.length) throw new Error("No separately approved/verified scope is available.")
      const scopeRef = await context.ui.dialog.select({ title: "Separately approved live scope (not a new approval)", options: scopes.map(row => ({
        title: `${row.pilot_id} · remaining USD ${row.accounting.remaining_usd}`, value: row.scope_ref })) })
      if (scopeRef === undefined) return
      const scope = scopes.find(row => row.scope_ref === scopeRef)
      const taskType = await context.ui.dialog.select({ title: "Explicit supported task category", options: scope.routes.map(row => ({ title: `${row.task_type} → ${row.model}`, value: row.task_type })) })
      if (taskType === undefined) return
      const route = scope.routes.find(row => row.task_type === taskType)
      const capabilities = [...new Set((route.local_tools ?? []).map(tool => tool.capability))]
      let requiredTools = []
      if (capabilities.length) {
        const required = await context.ui.dialog.prompt({ title: `Required reviewed local capabilities (${capabilities.join(", ")}; comma separated, blank = text only)` })
        if (required === undefined) return
        requiredTools = required.split(",").map(value => value.trim()).filter(Boolean)
        if (new Set(requiredTools).size !== requiredTools.length || requiredTools.some(value => !capabilities.includes(value))) throw new Error("Tool capabilities are outside the reviewed local function envelope.")
      }
      const taskLabel = await context.ui.dialog.prompt({ title: "New task label — metadata only", placeholder: "No code, prompts, outputs or secrets" })
      if (!taskLabel) return
      const selectedModel = await context.ui.dialog.select({ title: "Original manual model choice (policy ID, explicitly reported)", options: configuration.models.map(value => ({ title: value, value })) })
      if (selectedModel === undefined) return
      const override = await context.ui.dialog.select({ title: "Developer override for this NEW task only", options: [{ title: "Use the reviewed category route", value: "" },
        ...configuration.models.map(value => ({ title: value, value }))] })
      if (override === undefined) return
      const risk = await context.ui.dialog.confirm({ title: "Confirm justified low-risk, bounded task", message: "Only the evidenced category and explicitly reviewed local read/edit/test tools are supported. Unknown tool charges, unrestricted shell, subagents and remote/paid tools are refused. OpenCode permissions still apply. This cannot expand company scope.", label: { confirm: "This task fits", cancel: "Cancel" } })
      if (!risk) return
      const contextText = await context.ui.dialog.prompt({ title: "Required context tokens — explicit requirement, never guess" })
      const outputText = await context.ui.dialog.prompt({ title: "Maximum output/reasoning tokens per request — explicit bound" })
      const capText = await context.ui.dialog.prompt({ title: "Maximum total task cost USD — exact decimal, no default budget" })
      if (contextText === undefined || outputText === undefined || capText === undefined) return
      const contextTokens = Number(contextText), outputLimit = Number(outputText)
      if (!Number.isSafeInteger(contextTokens) || contextTokens < 1 || !Number.isSafeInteger(outputLimit) || outputLimit < 1
        || !/^\d+(\.\d+)?$/.test(capText) || !/[1-9]/.test(capText)) throw new Error("Unknown/invalid requirements cannot authorize delivery.")
      const confirmed = await context.ui.dialog.confirm({ title: "Create one NEW isolated delivery session — no prompt", message:
        `Repository: ${configuration.repository_ref}\nPilot: ${scope.pilot_id}\nTask: ${taskLabel}\nCategory: ${taskType}\nRequired local capabilities: ${requiredTools.join(", ") || "none (text only)"}\nOriginal manual choice: ${selectedModel}\nOverride: ${override || "none"}\nTask cap USD: ${capText}\nRequest output limit: ${outputLimit}\nCurrent work/model stays unchanged. No model runs here.`, label: { confirm: "Create new session", cancel: "Cancel" } })
      if (!confirmed) return
      sameContext(original)
      const result = await rpc.start({ scopeRef, repositoryRef: configuration.repository_ref, taskLabel, taskType, riskTags: ["low"],
        selectedModel, overrideModel: override || null, contextTokens, outputLimit, taskCapUSD: capText, clientTaskID: randomUUID(), requiredTools }, { location: original.location })
      if (!result.sessionCreated || result.executionSent !== false) throw new Error("No exact newly created bound session was returned.")
      // Navigate ONLY to the new root; never mutate/switch an unrelated active session.
      sameContext(original)
      context.ui.router.navigate({ type: "session", sessionID: result.sessionID })
      await feedback.refresh()
    }),
    end: run(async () => {
      const original = snapshot()
      if (original.route.type !== "session") throw new Error("Open the specific delivery task first.")
      const id = original.route.sessionID
      const checkIdle = () => {
        // OpenCode 2.0.21's TUI returns a bare string ("idle"); older shapes used { type }.
        // Only an explicitly idle session may end; unknown or any other state refuses.
        const execution = context.data.session.status(id)
        const kind = typeof execution === "string" ? execution : execution?.type
        if (kind !== "idle") throw new Error("Task is not known idle.")
      }
      checkIdle()
      // Quick sessions: report the model only when the company gateway shows every attempt
      // completed on the bound model at a known cost, with nothing unknown or reserved.
      let observed = null
      if (quickSessions.has(id)) {
        const current = await rpc.state({ sessionID: id }, { location: original.location })
        const delivery = current.delivery
        const attempts = delivery?.attempts ?? []
        if (current.task && current.task.reported_actual_model == null && delivery?.policy_model && Number(delivery.unknown_attempts) === 0
          && Number(delivery.attempt_reserved_usd) === 0 && Number(delivery.known_cost_usd) > 0 && attempts.length
          && attempts.every(attempt => attempt.outcome === "completed")) observed = delivery.policy_model
      }
      if (!await context.ui.dialog.confirm({ title: "End this task", message: observed
        ? `Close the task and report ${observed} as the model used (observed by the company gateway). This does not claim the work is good; costs are kept.`
        : "Close the task without claiming success or refunding unknown costs. Outstanding settlement survives close/revocation.", label: { confirm: "End task", cancel: "Cancel" } })) return
      sameContext(original); checkIdle()
      await rpc.end({ sessionID: id }, { location: original.location })
      quickSessions.delete(id)
      if (observed) {
        try {
          const current = await rpc.state({ sessionID: id }, { location: original.location })
          await rpc.feedback({ sessionID: id, action: "actual_model", expectedRevision: current.task.task_revision, value: observed }, { location: original.location })
        } catch { context.ui.toast.show({ title: "Tarkado delivery", message: "Task ended, but the model report was not recorded. Use /tarkado-delivery-report-model.", variant: "warning" }) }
      }
      await feedback.refresh()
    }),
  }
}

import { randomUUID } from "node:crypto"

export function taskLines(state) {
  const task = state?.task
  if (!task) return ["No explicit Tarkado task. Start one before work; manual model choice is unchanged."]
  return [
    `Task: ${task.task_label} — ${task.closed ? "explicitly ended" : "open"}`,
    `Selected: ${task.recommendation.effective_model ?? "Unknown"}`,
    `Suggested: ${task.recommendation.recommended_model ?? "Blocked"}`,
    `Fallback: ${task.recommendation.fallback_model}`,
    `Reason: ${task.recommendation.reason}`,
    `Confidence: ${task.recommendation.confidence} — rule label, not success probability`,
    `Policy: ${task.recommendation.policy_version}; current: ${task.policy_current ? "yes" : "no (historical)"}`,
    `Learner: ${task.learning?.version ?? "static/default"}; publication at task start: ${task.suggestion_context?.status ?? "not published"}`,
    `One-task response: ${task.response ?? "Unknown"}; reported actual: ${task.reported_actual_model ?? "Unknown"}`,
    `Observed primary attempt models: ${task.observed_attempt_models.join(", ") || "Unknown"}`,
    `Coverage: ${task.coverage_status}; gaps: ${task.gap_count}; multiple models: ${task.multiple_models}`,
    "Outcomes remain human reports. No live routing, extra model call, or provider usage verification.",
    ...(state.problem ? [state.problem] : []),
  ]
}

export function actions({ rpc, context, status, setStatus }) {
  const sessionID = (idle = false) => {
    const route = context.ui.router.current()
    if (route.type !== "session") throw new Error("Open a root OpenCode session first.")
    const execution = context.data.session.status(route.sessionID)
    if (idle && (execution === undefined || execution?.type === "running")) throw new Error("Wait for verified idle state; this connector does not switch or split active work.")
    return route.sessionID
  }
  const refresh = async () => {
    const route = context.ui.router.current()
    if (route.type !== "session") { setStatus({ task: null }); return }
    setStatus(await rpc.state({ sessionID: route.sessionID }, { location: context.location }))
  }
  const state = async () => { await refresh(); if (!status().task) throw new Error("Start an explicit task first."); return status().task }
  const checkContext = (id) => { if (sessionID() !== id) throw new Error("Session changed while editing feedback; no record submitted.") }
  const run = (fn) => async () => {
    try { await fn(); await refresh() }
    catch { context.ui.toast.show({ title: "Tarkado", message: "Action unavailable/refused. Review pairing, scope, pending observations, and task state in the browser.", variant: "error" }) }
  }
  return {
    refresh,
    connect: run(async () => { await rpc.connect({}, { location: context.location }); context.ui.toast.show({ message: "Tarkado connected. Explicit tasks only; model choice stays manual.", variant: "success" }) }),
    start: run(async () => {
      const id = sessionID(true)
      const selected = context.ui.model.current()
      if (!selected?.providerID || !selected?.id) throw new Error("No explicit selected model.")
      const configuration = await rpc.connect({}, { location: context.location })
      const taskLabel = await context.ui.dialog.prompt({ title: "Tarkado task label — metadata only", placeholder: "No prompt/code/output or secrets" })
      if (!taskLabel) return
      const taskType = await context.ui.dialog.select({ title: "Task category (declared, not inferred)", options: [
        { title: "Unknown", value: "" }, ...configuration.categories.map(value => ({ title: value, value }))] })
      const risk = await context.ui.dialog.select({ title: "Task risk — use low only when justified", options: [
        { title: "Unknown (safe fallback)", value: "" }, { title: "Low", value: "low" }, { title: "High", value: "high" }] })
      const tools = await context.ui.dialog.prompt({ title: "Required tools (comma separated; blank = not declared)" })
      const tokens = await context.ui.dialog.prompt({ title: "Required context tokens (blank = unknown, never guess)" })
      if (taskType === undefined || risk === undefined || tools === undefined || tokens === undefined) return
      const contextTokens = tokens === "" ? null : Number(tokens)
      if (contextTokens !== null && (!Number.isSafeInteger(contextTokens) || contextTokens < 0)) throw new Error("Invalid context requirement.")
      const accepted = await context.ui.dialog.confirm({ title: "Start one explicit Tarkado task", message:
        `Repository: ${configuration.repository_ref}\nTask: ${taskLabel}\nCategory: ${taskType || "Unknown"}\nRisk: ${risk || "Unknown"}\nSelected: ${selected.providerID}/${selected.id}\nOnly permitted metadata is retained. No model will run or be changed.`, label: { confirm: "Start task", cancel: "Cancel" } })
      if (!accepted) return
      if (sessionID(true) !== id) throw new Error("Session changed while selecting task metadata.")
      const finalModel = context.ui.model.current()
      if (finalModel?.providerID !== selected.providerID || finalModel?.id !== selected.id) throw new Error("Selected model changed; review the new task again.")
      await rpc.start({ sessionID: id, clientTaskID: randomUUID(), taskLabel, selectedModel: `${selected.providerID}/${selected.id}`,
        taskType: taskType || null, riskTags: risk ? [risk] : [], requiredTools: tools.split(",").map(s => s.trim()).filter(Boolean), contextTokens }, { location: context.location })
    }),
    accept: run(async () => { const id = sessionID(); const task = await state(); checkContext(id); await rpc.feedback({ sessionID: id, action: "response", expectedRevision: task.task_revision, value: "accept" }, { location: context.location }) }),
    reject: run(async () => { const id = sessionID(); const task = await state(); checkContext(id); await rpc.feedback({ sessionID: id, action: "response", expectedRevision: task.task_revision, value: "reject" }, { location: context.location }) }),
    reportModel: run(async () => {
      const id = sessionID()
      const task = await state()
      const model = await context.ui.dialog.prompt({ title: "Model actually used — your report, not execution proof", placeholder: task.observed_attempt_models[0] ?? "provider/model" })
      checkContext(id)
      if (model) await rpc.feedback({ sessionID: id, action: "actual_model", expectedRevision: task.task_revision, value: model }, { location: context.location })
    }),
    result: run(async () => {
      const id = sessionID()
      const task = await state()
      const desired = await context.ui.dialog.select({ title: "Desired engineering result (reported, not inferred from run completion)", options: [
        { title: "Unknown", value: "unknown" }, { title: "Yes", value: "true" }, { title: "No / failure", value: "false" }] })
      if (desired === undefined) return
      const tests = await context.ui.dialog.select({ title: "Tests passed?", options: [{ title: "Unknown", value: "unknown" }, { title: "Yes", value: "true" }, { title: "No", value: "false" }] })
      if (tests === undefined) return
      const evidence = await context.ui.dialog.prompt({ title: "Evidence reference (metadata only; required for known quality)", placeholder: "No test output/code/secrets" })
      if (evidence === undefined) return
      const bool = value => ({ unknown: null, true: true, false: false })[value]
      checkContext(id)
      const prior = task.current_result
      const changed = prior && !await context.ui.dialog.confirm({ title: "Append full result correction", message: "This correction keeps prior score/cost/latency and replaces quality/tests/evidence with the fields just entered. Earlier history remains; edit measurements in the browser.", label: { confirm: "Append correction", cancel: "Cancel" } })
      if (changed) return
      checkContext(id)
      await rpc.feedback({ sessionID: id, action: "result", expectedRevision: task.task_revision,
        value: { desired_result: bool(desired), tests_passed: bool(tests), score: null, cost_usd: null, latency_ms: null,
          ...(prior ? { score: prior.score, cost_usd: prior.cost_usd, latency_ms: prior.latency_ms } : {}),
          evidence_ref: evidence || null, supersedes: prior?.result_id ?? null } }, { location: context.location })
    }),
    close: run(async () => {
      const id = sessionID(true)
      if (await context.ui.dialog.confirm({ title: "End explicit task observation", message: "Wait until this task's work is done. Ending observation records no engineering success; unknowns and gaps remain.", label: { confirm: "End task", cancel: "Cancel" } })) {
        if (sessionID(true) !== id) throw new Error("Session changed during explicit close.")
        await rpc.close({ sessionID: id }, { location: context.location })
      }
    }),
    browser: run(async () => {
      const task = await state()
      await context.ui.dialog.alert({ title: "Open existing browser record", message: `Use your configured Tarkado browser origin + ${task.browser_path}\nSign in normally. No credential belongs in this URL. The connector does not launch a shell/browser process.` })
    }),
  }
}

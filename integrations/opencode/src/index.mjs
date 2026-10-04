import { Plugin } from "@opencode/plugin"
import { credentialFile, CompanyClient } from "./client.mjs"
import { Connector } from "./core.mjs"
import { Tarkado } from "./rpc.mjs"

export default Plugin.define({
  id: "tarkado.connector",
  async setup(ctx) {
    if (ctx.options.privateDeveloperService !== true) {
      throw new Error("Tarkado requires an explicitly operator-approved private single-developer OpenCode service context. Shared-service identity is unsupported.")
    }
    // Only an explicitly configured Tarkado credential is read. Never resolve provider connections.
    const configuration = await credentialFile(ctx.options.credentialFile)
    const connector = new Connector({ client: new CompanyClient(configuration), directory: ctx.location.directory,
      session: ctx.session, version: ctx.app.version })
    await ctx.rpc.register(Tarkado, {
      connect: () => connector.connect(),
      state: ({ sessionID }) => connector.state(sessionID),
      start: (input) => connector.newTask(input),
      feedback: (input) => connector.feedback(input),
      close: ({ sessionID }) => connector.close(sessionID),
    })
    // Read model/status fields only. Do not inspect prompt text, messages, headers, URLs, bodies, tools, or outputs.
    for (const kind of ["context", "compaction", "title", "generate"]) {
      await ctx.session.hook(kind, (event) => connector.capture({ sessionID: event.sessionID, model: event.model,
        kind: kind === "context" ? "primary" : kind }, "model_attempt"))
    }
    await ctx.session.hook("http.response", (event) => connector.capture({ sessionID: event.sessionID, kind: event.kind,
      model: event.model, response: { status: event.response.status } }, "http_status"))
    // The documented retry hook has no request-kind field. Do not guess it is primary.
    await ctx.session.hook("retry", (event) => connector.capture({ sessionID: event.sessionID, kind: "unknown", model: event.model,
      attempt: event.attempt, decision: { retry: event.decision.retry } }, "retry"))
    // Recovery requires only delegated company metadata; no OpenCode session enumeration.
    const recovery = setInterval(() => { void connector.connect().catch(() => {
      connector.problem = "Scoped connector unavailable/refused; manual choice unchanged."
    }) }, 30000)
    void connector.connect().catch(() => { connector.problem = "Pairing unavailable/refused; use browser renewal." })
    return () => { clearInterval(recovery); connector.unload() }
  },
})

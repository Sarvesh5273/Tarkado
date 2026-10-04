import { Plugin } from "@opencode/plugin"
import { credentialFile, CompanyClient } from "./client.mjs"
import { DeliveryCoordinator } from "./delivery-coordinator.mjs"
import { DeliveryRPC } from "./delivery-rpc.mjs"

// Separate opt-in entrypoint. The shipped observer remains recommendation-only.
export default Plugin.define({ id: "tarkado.delivery", async setup(ctx) {
  if (ctx.options.privateDeveloperService !== true || ctx.app.version !== "2.0.21") {
    throw new Error("Delivery requires an explicitly approved private developer context and validated OpenCode source version.")
  }
  const configuration = await credentialFile(ctx.options.credentialFile)
  const coordinator = new DeliveryCoordinator({ company: new CompanyClient(configuration), session: ctx.session,
    directory: ctx.location.directory, gatewayRef: ctx.options.gatewayRef, providerID: ctx.options.providerID,
    gatewayOrigin: ctx.options.gatewayOrigin })
  const rpc = await ctx.rpc.register(DeliveryRPC, { connect: () => coordinator.connect(), start: input => coordinator.newTask(input),
    state: input => coordinator.state(input.sessionID), feedback: input => coordinator.feedback(input), end: input => coordinator.end(input.sessionID) })
  const requests = await ctx.session.hook("http.request", event => coordinator.request(event))
  const websockets = await ctx.session.hook("experimental.ws.handshake", event => coordinator.websocket(event))
  const options = []
  for (const kind of ["context", "compaction", "title", "generate"]) options.push(await ctx.session.hook(kind, event => coordinator.prepareOptions(event)))
  return async () => { await rpc.dispose(); await requests.dispose(); await websockets.dispose(); for (const registration of options) await registration.dispose() }
} })

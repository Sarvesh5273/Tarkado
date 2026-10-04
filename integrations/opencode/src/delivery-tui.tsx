import { Plugin } from "@opencode/plugin/tui"
import { createSignal, For, Show } from "solid-js"
import { DeliveryRPC } from "./delivery-rpc.mjs"
import { deliveryActions, deliveryLines } from "./delivery-actions.mjs"

// Only the separate explicitly loaded delivery package exposes these commands.
export default Plugin.define({ id: "tarkado.delivery.cli", setup(context) {
  const [status, setStatus] = createSignal<any>({ task: null, delivery: null })
  const act = deliveryActions({ rpc: context.client.rpc(DeliveryRPC), context, status, setStatus })
  const commands = [["connect", "Inspect delivery setup", act.connect], ["start", "Create NEW bound task session (no prompt)", act.start],
    ["end", "End this delivery task; retain costs", act.end], ["accept", "Accept this suggestion only", act.accept],
    ["reject", "Reject this suggestion only", act.reject], ["report-model", "Report actual policy model used", act.reportModel],
    ["result", "Report eventual engineering result", act.result], ["browser", "Show private company record path", act.browser]] as const
  context.ui.slot({ append: "app", render: () => {
    context.keymap.layer(() => ({ mode: "global", commands: [
      { id: "tarkado.delivery.panel", title: "Inspect Tarkado delivery task", group: "Tarkado delivery", palette: true, slash: { name: "tarkado-delivery" },
        run: async () => { try { await act.refresh() } catch { setStatus({ task: null, problem: "Delivery metadata unavailable; no model changed." }) }; context.ui.panel.open("tarkado.delivery.task") } },
      ...commands.map(([id, title, run]) => ({ id: `tarkado.delivery.${id}`, title, group: "Tarkado delivery", palette: true,
        slash: { name: `tarkado-delivery-${id}` }, run })),
    ] }))
    return null
  } })
  context.ui.slot({ append: "prompt.footer.status", render: () => <text>Tarkado delivery · {status().task?.task_label ?? "no bound task"} · no silent switching</text> })
  context.ui.slot({ append: "session.panel", render: panel => <Show when={panel.name === "tarkado.delivery.task"}>
    <box flexDirection="column"><text>Explicit delivery — separate approval, fixed model</text>
      <For each={deliveryLines(status())}>{line => <text wrapMode="word">{line}</text>}</For>
      <text>/tarkado-delivery-start · /tarkado-delivery-end · /tarkado-delivery-report-model · /tarkado-delivery-result</text>
    </box>
  </Show> })
} })

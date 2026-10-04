import { Plugin } from "@opencode/plugin/tui"
import { createSignal, For, Show } from "solid-js"
import { Tarkado } from "./rpc.mjs"
import { actions, taskLines } from "./actions.mjs"

export default Plugin.define({
  id: "tarkado.connector.cli",
  setup(context) {
    const [status, setStatus] = createSignal<any>({ task: null, configured: false })
    const rpc = context.client.rpc(Tarkado)
    const act = actions({ rpc, context, status, setStatus })
    const commands = [
      ["connect", "Reconnect scoped Tarkado access", act.connect],
      ["start", "Start explicit Tarkado task", act.start],
      ["accept", "Accept this task's suggestion only", act.accept],
      ["reject", "Reject this task's suggestion only", act.reject],
      ["report-model", "Report actual model used", act.reportModel],
      ["result", "Report eventual task result / correction", act.result],
      ["end", "End explicit Tarkado task observation", act.close],
      ["browser", "Show existing browser task record", act.browser],
    ] as const
    context.ui.slot({ append: "app", render: () => {
      context.keymap.layer(() => ({ mode: "global", commands: [
        { id: "tarkado.panel", title: "Open Tarkado task panel", group: "Tarkado", palette: true, slash: { name: "tarkado" },
          run: async () => { try { await act.refresh() } catch { setStatus({ problem: "Connector unavailable; manual selection unchanged." }) }; context.ui.panel.open("tarkado.task") } },
        ...commands.map(([id, title, run]) => ({ id: `tarkado.${id}`, title, group: "Tarkado", palette: true,
          slash: { name: `tarkado-${id}` }, run })),
      ] }))
      return null
    } })
    context.ui.slot({ append: "prompt.footer.status", render: () => <text>Tarkado · shadow · {status().problem ? "observation gap/offline" : status().task ? status().task.task_label : "no explicit task"}</text> })
    context.ui.slot({ append: "session.panel", render: panel => <Show when={panel.name === "tarkado.task"}>
      <box flexDirection="column"><text>Tarkado — manual choice, explicit task</text>
        <For each={taskLines(status())}>{line => <text wrapMode="word">{line}</text>}</For>
        <text>Use /tarkado-start · /tarkado-accept · /tarkado-reject · /tarkado-report-model · /tarkado-end · /tarkado-result · /tarkado-browser</text>
      </box>
    </Show> })
    const timer = setInterval(() => { if (status().configured) void act.refresh().catch(() => setStatus(previous => ({ ...previous, problem: "Connector unavailable; manual choice unchanged." }))) }, 5000)
    return () => clearInterval(timer)
  },
})

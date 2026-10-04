import { Rpc } from "@opencode/plugin/rpc"

const string = { type: "string" }
const obj = (properties, required = Object.keys(properties)) => ({ type: "object", properties, required, additionalProperties: false })
const result = { type: "object" }

export const Tarkado = Rpc.define({
  id: "tarkado.connector.v1",
  methods: {
    connect: { input: obj({}), output: result },
    state: { input: obj({ sessionID: string }), output: result },
    start: { input: obj({ sessionID: string, clientTaskID: string, taskLabel: string, selectedModel: string,
      taskType: { anyOf: [string, { type: "null" }] }, riskTags: { type: "array", items: string },
      requiredTools: { type: "array", items: string }, contextTokens: { anyOf: [{ type: "integer", minimum: 0 }, { type: "null" }] } }), output: result },
    feedback: { input: obj({ sessionID: string, action: { type: "string", enum: ["response", "actual_model", "result"] },
      expectedRevision: { type: "integer", minimum: 1 }, value: { anyOf: [string, { type: "object" }] } }), output: result },
    close: { input: obj({ sessionID: string }), output: result },
  },
})

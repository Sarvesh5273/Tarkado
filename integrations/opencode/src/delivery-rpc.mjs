import { Rpc } from "@opencode/plugin/rpc"

const string = { type: "string" }
const object = properties => ({ type: "object", properties, required: Object.keys(properties), additionalProperties: false })
export const DeliveryRPC = Rpc.define({ id: "tarkado.delivery.v1", methods: {
  connect: { input: object({}), output: { type: "object" } },
  start: { input: object({ scopeRef: string, repositoryRef: string, taskLabel: string, taskType: string,
    riskTags: { type: "array", items: string }, selectedModel: string, contextTokens: { type: "integer", minimum: 1 },
    taskCapUSD: string, overrideModel: { anyOf: [string, { type: "null" }] } }), output: { type: "object" } },
  end: { input: object({ sessionID: string }), output: { type: "object" } },
} })

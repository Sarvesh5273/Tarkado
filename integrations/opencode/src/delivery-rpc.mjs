import { Rpc } from "@opencode/plugin/rpc"

const string = { type: "string" }
const object = (properties, required = Object.keys(properties)) => ({ type: "object", properties, required, additionalProperties: false })
export const DeliveryRPC = Rpc.define({ id: "tarkado.delivery.v1", methods: {
  connect: { input: object({}), output: { type: "object" } },
  state: { input: object({ sessionID: string }), output: { type: "object" } },
  start: { input: object({ scopeRef: string, repositoryRef: string, taskLabel: string, taskType: string,
    riskTags: { type: "array", items: string }, selectedModel: string, contextTokens: { type: "integer", minimum: 1 },
    taskCapUSD: string, outputLimit: { type: "integer", minimum: 1 }, clientTaskID: string,
    overrideModel: { anyOf: [string, { type: "null" }] }, requiredTools: { type: "array", items: { type: "string", enum: ["read", "edit", "test"] }, uniqueItems: true } },
    ["scopeRef", "repositoryRef", "taskLabel", "taskType", "riskTags", "selectedModel", "contextTokens", "taskCapUSD", "outputLimit", "clientTaskID", "overrideModel"]), output: { type: "object" } },
  feedback: { input: object({ sessionID: string, action: { type: "string", enum: ["response", "actual_model", "result"] },
    expectedRevision: { type: "integer", minimum: 1 }, value: { anyOf: [string, { type: "object" }] } }), output: { type: "object" } },
  end: { input: object({ sessionID: string }), output: { type: "object" } },
} })

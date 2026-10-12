import type { JSONSchema } from "json-schema-to-ts"
import { eventPayloadSchemas } from "./eventPayloadSchemas.js"
import type { ProducerPayload, WirePayload } from "./eventSchemaTypes.js"

/** Shared wire envelopes, producer types and documentation metadata. */
export interface EventDefinition {
  readonly type: string
  readonly operationId: string
  readonly summary: string
  readonly tags: readonly string[]
  readonly messageId: string
  readonly payload: JSONSchema
  readonly examples: readonly { readonly name: string, readonly payload: unknown }[]
}

const taskUpdatedSchema = {
  type: "object", additionalProperties: false, required: ["type", "task"],
  properties: { type: { const: "task.updated" }, task: { $ref: "TaskEventPayload" } },
} as const satisfies JSONSchema

const agentExecutionOpenedSchema = {
  type: "object", additionalProperties: false, required: ["type", "execution"],
  properties: { type: { const: "agent-execution.opened" }, execution: { $ref: "AgentExecutionEventPayload" } },
} as const satisfies JSONSchema

const agentExecutionUpdatedSchema = {
  type: "object", additionalProperties: false, required: ["type", "execution"],
  properties: { type: { const: "agent-execution.updated" }, execution: { $ref: "AgentExecutionEventPayload" } },
} as const satisfies JSONSchema

const openedExecution = {
  id: 2, evaluationId: null, agentType: "analyzer", status: "Waiting",
  result: null, error: null, inputTokens: null, outputTokens: null,
  createdAt: "2026-10-11T00:00:00.000Z", startedAt: null, finishedAt: null,
} as const

export const eventCatalog = [
  {
    type: "task.updated",
    operationId: "sendTaskUpdated",
    summary: "Broadcast task.updated notifications.",
    tags: ["Tasks"],
    messageId: "TaskUpdated",
    payload: taskUpdatedSchema,
    examples: [{ name: "queued", payload: {
      type: "task.updated",
      task: {
        id: 1, projectId: 3, description: "fetching acme/Demo",
        command: "git -C C:/workspace/Demo fetch", status: "Queued", kind: "fetch", exitCode: null,
      },
    } satisfies WirePayload<typeof taskUpdatedSchema, typeof eventPayloadSchemas> }, {
      name: "failed", payload: {
        type: "task.updated",
        task: { id: 1, projectId: 3, description: null, command: null, status: "Failed", kind: "fetch", exitCode: 1 },
      } satisfies WirePayload<typeof taskUpdatedSchema, typeof eventPayloadSchemas>,
    }],
  },
  {
    type: "agent-execution.opened",
    operationId: "sendAgentExecutionOpened",
    summary: "Broadcast agent-execution.opened notifications.",
    tags: ["Agent Executions"],
    messageId: "AgentExecutionOpened",
    payload: agentExecutionOpenedSchema,
    examples: [{ name: "waiting", payload: {
      type: "agent-execution.opened", execution: openedExecution,
    } satisfies WirePayload<typeof agentExecutionOpenedSchema, typeof eventPayloadSchemas> }],
  },
  {
    type: "agent-execution.updated",
    operationId: "sendAgentExecutionUpdated",
    summary: "Broadcast agent-execution.updated notifications.",
    tags: ["Agent Executions"],
    messageId: "AgentExecutionUpdated",
    payload: agentExecutionUpdatedSchema,
    examples: [{ name: "running", payload: {
      type: "agent-execution.updated",
      execution: { ...openedExecution, status: "Running", startedAt: "2026-10-11T00:00:01.000Z" },
    } satisfies WirePayload<typeof agentExecutionUpdatedSchema, typeof eventPayloadSchemas> }, {
      name: "completed", payload: {
        type: "agent-execution.updated",
        execution: {
          ...openedExecution, status: "Completed", result: '{"kind":"library"}', inputTokens: 1200, outputTokens: 180,
          startedAt: "2026-10-11T00:00:01.000Z", finishedAt: "2026-10-11T00:01:00.000Z",
        },
      } satisfies WirePayload<typeof agentExecutionUpdatedSchema, typeof eventPayloadSchemas>,
    }, {
      name: "failed", payload: {
        type: "agent-execution.updated",
        execution: { ...openedExecution, status: "Failed", error: "Agent-server unavailable", finishedAt: "2026-10-11T00:01:00.000Z" },
      } satisfies WirePayload<typeof agentExecutionUpdatedSchema, typeof eventPayloadSchemas>,
    }],
  },
] as const satisfies readonly EventDefinition[]

export type EventType = (typeof eventCatalog)[number]["type"]
export type TaskEvent = ProducerPayload<typeof taskUpdatedSchema, typeof eventPayloadSchemas>
export type AgentExecutionEvent = ProducerPayload<typeof agentExecutionOpenedSchema | typeof agentExecutionUpdatedSchema, typeof eventPayloadSchemas>
export type GatewayEvent = ProducerPayload<(typeof eventCatalog)[number]["payload"], typeof eventPayloadSchemas>
export type GatewayWireEvent = WirePayload<(typeof eventCatalog)[number]["payload"], typeof eventPayloadSchemas>

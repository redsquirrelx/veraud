import { eventCatalog, type EventDefinition } from "../realtime-gateway/eventCatalog.js"
import { eventPayloadSchemas } from "../realtime-gateway/eventPayloadSchemas.js"
import { asyncApiMetadata } from "./asyncApiMetadata.js"

/** Translate schema IDs used for type inference into document-local references. */
function documentSchema(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(documentSchema)
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value)
      .filter(([key]) => key !== "$id")
      .map(([key, item]) => {
        if (key === "$ref" && typeof item === "string") {
          if (!eventPayloadSchemas.some((schema) => schema.$id === item)) {
            throw new Error(`Unknown event payload schema reference: ${item}`)
          }
          return [key, `#/components/schemas/${item}`]
        }
        return [key, documentSchema(item)]
      }))
  }
  return value
}

/** Pure document builder shared by generation, checks and contract tests. */
export function buildAsyncApiDocument(events: readonly EventDefinition[] = eventCatalog) {
  if (new Set(events.map((event) => event.type)).size !== events.length) {
    throw new Error("Duplicate WebSocket event discriminator")
  }
  if (new Set(events.map((event) => event.operationId)).size !== events.length) {
    throw new Error("Duplicate AsyncAPI operation ID")
  }
  if (new Set(events.map((event) => event.messageId)).size !== events.length) {
    throw new Error("Duplicate AsyncAPI message ID")
  }

  return {
    ...structuredClone(asyncApiMetadata),
    channels: {
      realtime: {
        ...structuredClone(asyncApiMetadata.channels.realtime),
        messages: Object.fromEntries(events.map((event) => [event.messageId, {
          $ref: `#/components/messages/${event.messageId}`,
        }])),
      },
    },
    operations: Object.fromEntries(events.map((event) => [event.operationId, {
      action: "send",
      channel: { $ref: "#/channels/realtime" },
      summary: event.summary,
      tags: event.tags.map((name) => ({ name })),
      messages: [{ $ref: `#/channels/realtime/messages/${event.messageId}` }],
    }])),
    components: {
      schemas: Object.fromEntries(eventPayloadSchemas.map((schema) => [schema.$id, documentSchema(schema)])),
      messages: Object.fromEntries(events.map((event) => [event.messageId, {
        name: event.type,
        title: event.type,
        summary: event.summary,
        contentType: "application/json",
        payload: documentSchema(event.payload),
        examples: structuredClone(event.examples),
      }])),
    },
  }
}

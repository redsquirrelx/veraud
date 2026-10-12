import type { FromSchema, JSONSchema } from "json-schema-to-ts"

type SchemaReference = JSONSchema & { readonly $id: string }

/** JSON payload after JSON.stringify: date-time values are strings. */
export type WirePayload<Schema extends JSONSchema, References extends readonly SchemaReference[] = []> = FromSchema<Schema, {
  references: [...References]
}>

/** Existing producers supply Dates; serialization still belongs to the gateway. */
export type ProducerPayload<Schema extends JSONSchema, References extends readonly SchemaReference[] = []> = FromSchema<Schema, {
  references: [...References]
  deserialize: [{
    pattern: { type: "string", format: "date-time" }
    output: Date
  }]
}>

import { stringify } from "yaml"
import { buildAsyncApiDocument } from "./buildAsyncApiDocument.js"

export const asyncApiFile = new URL("./asyncapi.yaml", import.meta.url)

/** Stable output: no timestamps, environment substitution or runtime state. */
export function serializeAsyncApi(): string {
  return "# Generated from the TypeScript event catalog and metadata. Do not edit manually.\n"
    + stringify(buildAsyncApiDocument(), { lineWidth: 100 })
}

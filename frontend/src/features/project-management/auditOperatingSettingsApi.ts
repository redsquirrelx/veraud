import { requestJson } from "../../infrastructure/http-client/httpClient.ts"

export interface ConfigSchema {
  $ref?: string
  $defs?: Record<string, ConfigSchema>
  anyOf?: ConfigSchema[]
  type?: string
  properties?: Record<string, ConfigSchema>
  default?: unknown
  minimum?: number
  maximum?: number
  minLength?: number
  description?: string
}

export interface AuditSettingsDescriptor {
  schema: ConfigSchema
  values: Record<string, unknown>
}

async function request(attribute: string, values?: Record<string, unknown>, signal?: AbortSignal) {
  return requestJson<AuditSettingsDescriptor>(`/api/audit-settings/${encodeURIComponent(attribute)}`, "Could not load audit settings", {
    method: values ? "PUT" : "GET", signal,
    ...(values ? { headers: { "content-type": "application/json" }, body: JSON.stringify(values) } : {}),
  })
}

export const getAuditSettings = (attribute: string, signal?: AbortSignal) => request(attribute, undefined, signal)
export const saveAuditSettings = (attribute: string, values: Record<string, unknown>) => request(attribute, values)

export function resolveSchema(schema: ConfigSchema, root: ConfigSchema): ConfigSchema {
  if (schema.$ref) return resolveSchema(root.$defs?.[schema.$ref.split("/").at(-1)!] ?? {}, root)
  if (schema.anyOf) return resolveSchema(schema.anyOf.find((item) => item.type !== "null") ?? {}, root)
  return schema
}

export interface ConfigField { path: string[], schema: ConfigSchema }

export function configFields(root: ConfigSchema): ConfigField[] {
  const fields: ConfigField[] = []
  function visit(schema: ConfigSchema, path: string[]) {
    const resolved = resolveSchema(schema, root)
    if (resolved.properties) {
      for (const [name, child] of Object.entries(resolved.properties)) {
        // Legacy security-specific output values are normalized into agent_defaults.
        // Offer exactly one output control in the category drawer.
        if (name === "max_output_tokens" && path[0] === "security_config") continue
        visit(child, [...path, name])
      }
    } else if (["integer", "number", "string"].includes(resolved.type ?? "")) fields.push({ path, schema: resolved })
  }
  visit(root, [])
  return fields
}

export function fieldValue(values: Record<string, unknown>, path: string[]): string {
  let current: unknown = values
  for (const key of path) current = current !== null && typeof current === "object" ? (current as Record<string, unknown>)[key] : undefined
  return current === null || current === undefined ? "" : String(current)
}

export function settingsValues(fields: ConfigField[], form: Record<string, string>): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const field of fields) {
    const value = form[field.path.join(".")]?.trim()
    if (!value) continue
    const numeric = field.schema.type !== "string"
    const parsed = numeric ? Number(value) : value
    if (numeric && (!Number.isFinite(parsed) || (field.schema.type === "integer" && !Number.isSafeInteger(parsed))
      || (field.schema.minimum !== undefined && Number(parsed) < field.schema.minimum)
      || (field.schema.maximum !== undefined && Number(parsed) > field.schema.maximum))) throw new Error(field.path.join("."))
    let target = result
    for (const key of field.path.slice(0, -1)) target = (target[key] ??= {}) as Record<string, unknown>
    target[field.path.at(-1)!] = parsed
  }
  return result
}

export interface AuditAttributeDraft {
  descriptor?: AuditSettingsDescriptor
  form: Record<string, string>
}

export function auditDraftValues(attribute: string, draft?: AuditAttributeDraft) {
  if (!draft?.descriptor) return {}
  return settingsValues(configFields(draft.descriptor.schema).filter((field) =>
    field.path[0] === "agent_defaults" || field.path[0] === (attribute === "security" ? "security_config" : "functional_config")), draft.form)
}

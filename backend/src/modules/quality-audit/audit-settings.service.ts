import type { PrismaClient } from "../../generated/prisma/client.js"
import type { AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"

export class AuditSettingsError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as Record<string, unknown> : {}

function merge(base: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const result = { ...base }
  for (const [key, value] of Object.entries(patch)) result[key] = value !== null && typeof value === "object" && !Array.isArray(value)
    ? merge(object(result[key]), object(value)) : value
  return result
}

/** Read legacy security output settings as the same canonical generic field. */
function canonicalOutput(values: Record<string, unknown>): Record<string, unknown> {
  const security = object(values.security_config)
  if (security.max_output_tokens === undefined) return values
  const { max_output_tokens, ...rest } = security
  return { ...values, security_config: rest,
    agent_defaults: { ...object(values.agent_defaults), max_output_tokens } }
}

export class AuditSettingsService {
  constructor(private db: PrismaClient, private serverUrl?: string) {}

  private async remote(attribute: string, values?: Record<string, unknown>) {
    if (!["maintainability", "security", "functional_adequacy"].includes(attribute)) throw new AuditSettingsError("Unknown quality attribute", 400)
    if (!this.serverUrl) throw new AuditSettingsError("No agent-server URL configured", 503)
    let response: Response
    try {
      response = await fetch(`${this.serverUrl}/api/audits/configuration/${attribute}${values ? "/validate" : ""}`, {
        method: values ? "POST" : "GET", headers: { "content-type": "application/json" },
        ...(values ? { body: JSON.stringify(values) } : {}), signal: AbortSignal.timeout(10000),
      })
    } catch { throw new AuditSettingsError("Could not reach the agent-server configuration service", 503) }
    const result = object(await response.json())
    if (!response.ok) throw new AuditSettingsError(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail), response.status === 422 ? 422 : 503)
    return result
  }

  async get(attribute: string) {
    const descriptor = await this.remote(attribute)
    const rows = await this.db.auditSettings.findMany({ where: { attribute: { in: ["global", attribute] } } })
    return { ...descriptor, values: canonicalOutput(Object.assign({}, ...rows.map((row) => JSON.parse(row.options) as object))) }
  }

  async save(attribute: string, values: Record<string, unknown>) {
    const validated = canonicalOutput(object((await this.remote(attribute, canonicalOutput(values))).values))
    const { audit_budget, ...specific } = validated
    await this.db.$transaction([
      this.db.auditSettings.upsert({ where: { attribute }, create: { attribute, options: JSON.stringify(specific) }, update: { options: JSON.stringify(specific) } }),
      this.db.auditSettings.upsert({ where: { attribute: "global" }, create: { attribute: "global", options: JSON.stringify(audit_budget ? { audit_budget } : {}) },
        update: { options: JSON.stringify(audit_budget ? { audit_budget } : {}) } }),
    ])
    return { values: validated }
  }

  async executionOptions(attributes: string[], explicit: AuditOperatingOptions): Promise<AuditOperatingOptions> {
    explicit = canonicalOutput(explicit as Record<string, unknown>) as AuditOperatingOptions
    const rows = await this.db.auditSettings.findMany({ where: { attribute: { in: ["global", ...attributes] } } })
    const stored = new Map(rows.map((row) => [row.attribute, canonicalOutput(object(JSON.parse(row.options)))]))
    const selected: Record<string, Record<string, unknown>> = {}
    for (const attribute of attributes) {
      const values = merge(stored.get(attribute) ?? {}, canonicalOutput(explicit.attribute_options?.[attribute] ?? {}))
      for (const key of ["agent_defaults", ...(attribute === "maintainability" ? ["call_limits"]
        : attribute === "security" ? ["security_config"] : ["functional_config"])] as const) {
        const patch = explicit[key as keyof AuditOperatingOptions]
        if (patch) values[key] = merge(object(values[key]), object(patch))
      }
      if (Object.keys(values).length) selected[attribute] = values
    }
    return { ...stored.get("global"), ...explicit, ...(Object.keys(selected).length ? { attribute_options: selected } : {}) }
  }
}

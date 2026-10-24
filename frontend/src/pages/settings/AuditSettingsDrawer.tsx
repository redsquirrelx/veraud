import { useEffect, useId, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { Button, Drawer, Spinner } from "../../shared/ui-kit/index.ts"
import { configFields, fieldValue, getAuditSettings, saveAuditSettings, settingsValues,
  type AuditSettingsDescriptor } from "./auditSettingsApi.ts"

interface Props { attribute: string, label: string, open: boolean, onClose: () => void }
interface AuditSettingsError { key: ParseKeys<"settings">, detail?: string }

const fieldLabelKeys: Record<string, ParseKeys<"settings">> = {
  "audit_budget.max_total_tokens": "audit.drawer.fields.sharedTotalTokens",
  "agent_defaults.max_context_characters": "audit.drawer.fields.contextCharacters",
  "agent_defaults.max_output_tokens": "agents.drawer.maxTokens",
  "agent_defaults.max_total_tokens": "audit.drawer.fields.personalTokenBudget",
  "agent_defaults.max_model_calls": "audit.drawer.fields.maxModelCalls",
  "agent_defaults.max_tool_calls": "audit.drawer.fields.maxToolCalls",
  "security_config.max_scan_files": "audit.drawer.fields.maxScanFiles",
  "functional_config.retrieval_top_k": "audit.drawer.fields.retrievalTopK",
}

export function AuditSettingsDrawer({ attribute, label, open, onClose }: Props) {
  const { t } = useTranslation("settings")
  const id = useId()
  const [descriptor, setDescriptor] = useState<AuditSettingsDescriptor | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [initial, setInitial] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<AuditSettingsError | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    getAuditSettings(attribute, controller.signal).then((value) => {
      if (controller.signal.aborted) return
      const values = Object.fromEntries(configFields(value.schema).map((field) => [field.path.join("."), fieldValue(value.values, field.path)]))
      setDescriptor(value); setForm(values); setInitial(values); setLoading(false)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof ApiError && cause.messageSource !== "client"
          ? { key: "audit.drawer.loadFailedWithDetail", detail: cause.message } : { key: "audit.drawer.loadFailed" })
        setLoading(false)
      }
    })
    return () => controller.abort()
  }, [attribute, open, attempt])
  const fields = descriptor ? configFields(descriptor.schema) : []
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  let valid = true
  try { settingsValues(fields, form) } catch { valid = false }
  const groups = ["audit_budget", "call_limits", "security_config", "functional_config", "agent_defaults"] as const
  const headings = {
    audit_budget: t("audit.drawer.sharedBudget"), call_limits: t("audit.drawer.callLimits"),
    security_config: t("audit.drawer.securityOptions"), functional_config: t("audit.drawer.functionalOptions"),
    agent_defaults: t("audit.drawer.agentDefaults"),
  }
  async function save() {
    if (!descriptor || !dirty || !valid || saving) return
    setSaving(true); setError(null)
    try { await saveAuditSettings(attribute, settingsValues(fields, form)); onClose() }
    catch (cause) {
      setError(cause instanceof ApiError && cause.messageSource !== "client"
        ? { key: "audit.drawer.saveFailedWithDetail", detail: cause.message } : { key: "audit.drawer.saveFailed" })
    }
    finally { setSaving(false) }
  }
  return <Drawer open={open} title={t("audit.drawer.title", { category: label })}
    description={t("audit.drawer.description")} onClose={() => { if (!saving) onClose() }}
    footer={<>
      <Button variant="secondary" disabled={saving} onClick={onClose}>{t("agents.drawer.cancel")}</Button>
      <Button disabled={!descriptor || loading || saving || !dirty || !valid} loading={saving}
        onClick={() => void save()}>{t("agents.drawer.saveChanges")}</Button>
    </>}>
    <form className="settings-agent-editor" onSubmit={(event) => { event.preventDefault(); void save() }}>
      {error && <p role="alert" className="settings-error">{t(error.key, error.detail === undefined ? {} : { detail: error.detail })}</p>}
      {!descriptor && !error && <Spinner />}
      {!descriptor && error && <Button variant="secondary" onClick={() => { setError(null); setLoading(true); setAttempt((value) => value + 1) }}>{t("agents.retry")}</Button>}
      {descriptor && groups.map((group) => {
        const members = fields.filter((field) => field.path[0] === group)
        if (!members.length) return null
        return <section className="settings-agent-editor-section" key={group} aria-label={headings[group]}>
          <h3>{headings[group]}</h3>
          {group === "audit_budget" && <p className="settings-hint">{t("audit.drawer.sharedBudgetHint")}</p>}
          {group === "agent_defaults" && <p className="settings-hint">{t("audit.drawer.agentDefaultsHint")}</p>}
          <div className="settings-agent-parameters">
            {members.map(({ path, schema }) => {
              const key = path.join(".")
              const numeric = schema.type !== "string"
              const labelKey = fieldLabelKeys[key]
              return <div className="settings-agent-parameter" key={key}>
                <label className="ui-text-input" htmlFor={`${id}-${key}`}>
                  <span className="ui-item-legend">{labelKey ? t(labelKey) : path.slice(1).join(" · ")}</span>
                  <input id={`${id}-${key}`} className="ui-input" type={numeric ? "number" : "text"}
                    value={form[key] ?? ""} min={schema.minimum} max={schema.maximum} minLength={schema.minLength}
                    step={schema.type === "integer" ? "1" : "any"} disabled={saving}
                    placeholder={schema.default === undefined || schema.default === null ? t("agents.drawer.defaultPlaceholder") : String(schema.default)}
                    onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))} />
                </label>
                {schema.description && <span className="settings-hint">{schema.description}</span>}
              </div>
            })}
          </div>
        </section>
      })}
      {descriptor && <p className="settings-hint">{t("audit.drawer.defaultsHint")}</p>}
    </form>
  </Drawer>
}

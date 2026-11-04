import { useEffect, useId, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button, Spinner } from "../../shared/ui-kit/index.ts"
import "../../shared/ui-kit/Field.css"
import { AuditAttributeSummary } from "./AuditAttributeSummary.tsx"
import type { AuditAgentCatalog } from "./auditAgentCatalog.ts"
import { configFields, fieldValue, getAuditSettings, auditDraftValues, type AuditAttributeDraft, type AuditSettingsDescriptor } from "./auditOperatingSettingsApi.ts"

export function AuditAttributeConfiguration({ attribute, catalog, draft, onChange }: {
  attribute: "security" | "functional_adequacy", catalog: AuditAgentCatalog, draft: AuditAttributeDraft,
  onChange: (draft: AuditAttributeDraft) => void,
}) {
  const { t } = useTranslation("projects")
  const id = useId()
  const [advanced, setAdvanced] = useState(Boolean(draft.descriptor))
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  // Drafts stay in the parent; schema loading never writes global settings.
  const [loaded, setLoaded] = useState<AuditSettingsDescriptor | null>(null)
  useEffect(() => {
    if (!advanced || draft.descriptor || loaded) return
    const controller = new AbortController()
    getAuditSettings(attribute, controller.signal).then((descriptor) => {
      if (!controller.signal.aborted) setLoaded(descriptor)
    }, () => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [advanced, attribute, draft.descriptor, loaded, attempt])
  const descriptor = draft.descriptor ?? loaded
  const fields = descriptor ? configFields(descriptor.schema).filter((field) =>
    field.path[0] === "agent_defaults" || field.path[0] === (attribute === "security" ? "security_config" : "functional_config")) : []
  let valid = true
  try { if (descriptor) auditDraftValues(attribute, { descriptor, form: draft.form }) } catch { valid = false }
  return <div className="quality-audit-attribute-configuration">
    <p className="label">{t(attribute === "security" ? "qualityAudits.setup.securityScope" : "qualityAudits.setup.functionalScope")}</p>
    <AuditAttributeSummary attribute={attribute} catalog={catalog} />
    <p className="label">{t("qualityAudits.setup.inheritedSettings")}</p>
    <Button variant="secondary" aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}>{t("qualityAudits.setup.advanced")}</Button>
    {advanced && <div>
      <p className="label">{t("qualityAudits.setup.runOnly")}</p>
      {!descriptor && !failed && <Spinner />}
      {!descriptor && failed && <div role="alert"><p>{t("qualityAudits.setup.optionsFailed")}</p>
        <Button variant="secondary" onClick={() => { setFailed(false); setAttempt((value) => value + 1) }}>{t("qualityAudits.results.retry")}</Button>
      </div>}
      {fields.map(({ path, schema }) => {
        const key = path.join(".")
        const numeric = schema.type !== "string"
        const saved = descriptor ? fieldValue(descriptor.values, path) : ""
        return <label className="ui-field ui-text-input" htmlFor={`${id}-${key}`} key={key}>
          <span className="ui-field-label">{path.join(" · ")}</span>
          <input className="ui-input" id={`${id}-${key}`} type={numeric ? "number" : "text"}
            min={schema.minimum} max={schema.maximum} minLength={schema.minLength} step={schema.type === "integer" ? "1" : "any"}
            value={draft.form[key] ?? ""} placeholder={saved || (schema.default == null ? "" : String(schema.default))}
            onChange={(event) => { if (descriptor) onChange({ descriptor, form: { ...draft.form, [key]: event.target.value } }) }} />
          {schema.description && <span className="label">{schema.description}</span>}
        </label>
      })}
      {!valid && <p role="alert">{t("qualityAudits.setup.invalidOptions")}</p>}
    </div>}
  </div>
}

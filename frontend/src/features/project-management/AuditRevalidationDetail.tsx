import { useEffect, useRef } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button, ChevronLeftIcon } from "../../shared/ui-kit/index.ts"
import { formatDateTime, formatNumber } from "../../shared/i18n/format.ts"
import type { AuditRevalidation } from "./AuditValidationHistory.tsx"
import "./AuditRevalidationDetail.css"

type FindingState = "resolved" | "persistent" | "inconclusive"
const tones = { resolved: "success", persistent: "danger", inconclusive: "warning" } as const

// Illustrative results only; totals are derived from this same list.
const findings: { id: string, state: FindingState, en: string, es: string }[] = [
  { id: "F-001", state: "persistent", en: "Architecture boundary violation", es: "Violación de límites de arquitectura" },
  { id: "F-002", state: "resolved", en: "Excessive coupling", es: "Acoplamiento excesivo" },
  { id: "F-003", state: "inconclusive", en: "Duplicated responsibility", es: "Responsabilidad duplicada" },
  { id: "F-004", state: "resolved", en: "Missing input validation", es: "Falta de validación de entradas" },
  { id: "F-005", state: "resolved", en: "Unreachable error handler", es: "Manejador de errores inalcanzable" },
  { id: "F-006", state: "persistent", en: "Circular dependency", es: "Dependencia circular" },
  { id: "F-007", state: "resolved", en: "Missing regression coverage", es: "Falta de cobertura de regresión" },
  { id: "F-008", state: "resolved", en: "Inconsistent return contract", es: "Contrato de retorno inconsistente" },
]
const states: FindingState[] = ["resolved", "persistent", "inconclusive"]

export function AuditRevalidationDetail({ revalidation, onBack }: {
  revalidation: AuditRevalidation & { number: number }, onBack: () => void,
}) {
  const { i18n } = useTranslation("projects")
  const spanish = i18n.resolvedLanguage?.startsWith("es")
  const labels = spanish ? {
    back: "Volver al historial", completed: "Completada", findings: "Hallazgos revalidados",
    resolved: "Resueltos", persistent: "Persistentes", inconclusive: "No concluyentes",
    sample: "Vista conceptual con datos de ejemplo.", summary: "Resumen de la revalidación",
  } : {
    back: "Back to history", completed: "Completed", findings: "Revalidated findings",
    resolved: "Resolved", persistent: "Persistent", inconclusive: "Inconclusive",
    sample: "Conceptual view with sample data.", summary: "Revalidation summary",
  }
  const title = `Revalidation #${revalidation.number}`
  const findingLabels = spanish
    ? { resolved: "Resuelto", persistent: "Persistente", inconclusive: "No concluyente" }
    : { resolved: "Resolved", persistent: "Persistent", inconclusive: "Inconclusive" }
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { heading.current?.focus() }, [])

  return <section className="audit-revalidation-detail" aria-label={title}>
    <div className="audit-revalidation-back"><Button variant="secondary" onClick={onBack}><ChevronLeftIcon />{labels.back}</Button></div>
    <header className="audit-revalidation-detail-header">
      <h3 ref={heading} tabIndex={-1}>{title}</h3>
      <Badge tone="success">{labels.completed}</Badge>
    </header>
    <div className="audit-revalidation-detail-meta">
      <code title={revalidation.commitHash}>Commit {revalidation.commitHash.slice(0, 7)}</code>
      <time dateTime={revalidation.createdAt}>{formatDateTime(revalidation.createdAt)}</time>
    </div>
    <dl className="audit-revalidation-summary" aria-label={labels.summary}>
      {states.map((state) => <div key={state}>
        <dt>{labels[state]}</dt>
        <dd>{formatNumber(findings.filter((finding) => finding.state === state).length)}</dd>
      </div>)}
    </dl>
    <section className="audit-revalidation-findings" aria-label={labels.findings}>
      <h4>{labels.findings}</h4>
      <ul>
        {findings.map((finding) => <li key={finding.id}>
          <div><code>{finding.id}</code><h5>{spanish ? finding.es : finding.en}</h5></div>
          <Badge tone={tones[finding.state]}>{findingLabels[finding.state]}</Badge>
        </li>)}
      </ul>
    </section>
    <p className="label audit-revalidation-sample">{labels.sample}</p>
  </section>
}

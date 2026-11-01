import { useTranslation } from "react-i18next"
import { formatNumber } from "../../shared/i18n/format.ts"
import type { ExecutionEvent } from "./executionEventsApi.ts"
import { eventMetricLabels, executionEventPresentation } from "./executionEventPresentation.ts"

export function ExecutionEventDescription({ event, names, detailed = false }: { event: ExecutionEvent, names: Map<string, string>, detailed?: boolean }) {
  const { i18n } = useTranslation("projects")
  const es = i18n.resolvedLanguage?.startsWith("es") === true
  const presentation = executionEventPresentation(event, es ? "es" : "en", names)
  const priority = ["http_status", "attempt", "retry", "delay_seconds", "wait_seconds", "seconds", "input_tokens", "output_tokens", "cache_hit", "attempts", "estimated_tokens", "phase_sequence"]
  const metrics = priority.filter((key) => key in event.metadata).map((key) => [key, event.metadata[key]] as const)
    .filter(([, value]) => typeof value === "boolean" || typeof value === "number" && Number.isFinite(value))
  const renderMetrics = (entries: typeof metrics) => entries.length > 0 && <dl className="audit-chronology-metrics">{entries.map(([key, value]) => <div key={key}>
    <dt>{eventMetricLabels[key][es ? 0 : 1]}</dt>
    <dd>{typeof value === "boolean" ? value ? es ? "Sí" : "Yes" : "No" : formatNumber(value, { maximumFractionDigits: 3 })}</dd>
  </div>)}</dl>
  const references = [
    [es ? "Tipo de evento" : "Event type", event.kind],
    [es ? "Operación registrada" : "Recorded operation", presentation.operation],
    [es ? "Agente" : "Agent", event.agentId ? names.get(event.agentId) ?? event.agentId : null],
    [es ? "Invocación" : "Invocation", event.invocationId],
    [es ? "Acción" : "Action", event.actionId],
    [es ? "Acción padre" : "Parent action", event.parentActionId],
    [es ? "Llamada de origen" : "Source call", event.sourceId],
    [es ? "Evento" : "Event", event.eventId],
    [es ? "Flujo de origen" : "Source stream", event.streamId],
    [es ? "Secuencia de origen" : "Source sequence", String(event.sequence)],
  ]
  if (!detailed) return <span className="audit-chronology-description">
    <strong title={presentation.title}>{presentation.title}</strong>
    <span className="audit-chronology-metrics">{metrics.slice(0, 3).map(([key, value]) => <span key={key}>
      {eventMetricLabels[key][es ? 0 : 1]}: {typeof value === "boolean" ? value ? es ? "Sí" : "Yes" : "No" : formatNumber(value, { maximumFractionDigits: 3 })}
    </span>)}</span>
  </span>
  return <div className="audit-event-description-details">
      <p>{presentation.description}</p>
      {!presentation.operation && /^(tool|model|node|phase|activity|wait)\./.test(event.kind) && <p>
        {es ? "No se registró el nombre específico de la operación." : "The specific operation name was not recorded."}
      </p>}
      {renderMetrics(metrics.filter(([key]) => key !== "seconds"))}
      <h3>{es ? "Referencias técnicas" : "Technical references"}</h3>
      <dl className="audit-event-modal-fields">{references.filter(([, value]) => value != null).map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{value}</code></dd></div>)}</dl>
  </div>
}

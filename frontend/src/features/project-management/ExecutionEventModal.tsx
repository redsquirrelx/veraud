import { useEffect, useRef } from "react"
import { createPortal } from "react-dom"
import { useTranslation } from "react-i18next"
import { Modal } from "../../shared/ui-kit/index.ts"
import { auditStateFrom } from "../../shared/audit-monitor/auditStatus.ts"
import { useAuditStateLabel } from "../../shared/audit-monitor/monitorLabels.ts"
import { formatDateTime, formatNumber } from "../../shared/i18n/format.ts"
import { ExecutionEventDescription } from "./ExecutionEventDescription.tsx"
import { executionEventPresentation } from "./executionEventPresentation.ts"
import type { ExecutionEvent } from "./executionEventsApi.ts"

export function ExecutionEventModal({ event, path, names, onClose }: {
  event: ExecutionEvent, path: string, names: Map<string, string>, onClose: () => void,
}) {
  const { i18n } = useTranslation("projects")
  const es = i18n.resolvedLanguage?.startsWith("es") === true
  const stateLabel = useAuditStateLabel()
  const content = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    content.current?.closest('[role="dialog"]')?.querySelector<HTMLButtonElement>("button")?.focus()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [])
  const presentation = executionEventPresentation(event, es ? "es" : "en", names)
  const state = event.status === "rejected" ? "failed" : event.status ? auditStateFrom(event.status, null) : "unknown"
  const status = event.status === "rejected" ? es ? "Rechazado" : "Rejected" : event.status === "timeout"
    ? es ? "Tiempo agotado" : "Timed out" : stateLabel(state)
  const seconds = event.metadata.seconds
  const missing = es ? "No registrado" : "Not recorded"
  return createPortal(<div className="audit-event-modal" onKeyDown={(keyboard) => {
    if (keyboard.key === "Tab") {
      // The shared modal currently has a single focusable control: Close.
      keyboard.preventDefault()
      content.current?.closest('[role="dialog"]')?.querySelector<HTMLButtonElement>("button")?.focus()
    }
    if (keyboard.key === "Escape") {
      keyboard.stopPropagation()
      onClose()
    }
  }}><Modal open label={es ? "Detalles del evento" : "Event details"} title={presentation.title} onClose={onClose}>
    <div className="audit-event-modal-content" ref={content}>
      <dl className="audit-event-modal-fields">
        <div><dt>{es ? "Ruta de ejecución" : "Execution path"}</dt><dd>{path}</dd></div>
        <div><dt>{es ? "Fecha del evento" : "Occurred at"}</dt><dd><time dateTime={event.occurredAt}>{formatDateTime(event.occurredAt, { dateStyle: "short", timeStyle: "medium" })}</time></dd></div>
        <div><dt>{es ? "Estado" : "Status"}</dt><dd data-state={state}>{status}</dd></div>
        <div><dt>{es ? "Duración" : "Duration"}</dt><dd>{typeof seconds === "number" && Number.isFinite(seconds) ? `${formatNumber(seconds, { maximumFractionDigits: 3 })} s` : missing}</dd></div>
        <div><dt>{es ? "Mensaje asociado" : "Associated message"}</dt><dd>{es ? "No se registró un mensaje asociado. La descripción siguiente explica el tipo de evento, no un mensaje original del proveedor." : "No associated message was recorded. The description below explains the event type, not an original provider message."}</dd></div>
      </dl>
      <ExecutionEventDescription event={event} names={names} detailed />
    </div>
  </Modal></div>, document.body)
}

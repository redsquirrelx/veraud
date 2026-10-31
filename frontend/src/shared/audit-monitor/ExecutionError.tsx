import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Button, Modal } from "../ui-kit/index.ts"
import { useMonitorLabels } from "./monitorLabels.ts"
import { formatDateTime } from "../i18n/format.ts"
import { readExecutionErrorDetail, type ExecutionErrorDetail } from "../../infrastructure/http-client/executionErrorDetail.ts"
import "./ExecutionError.css"

export function ExecutionErrorIndicator({ inherited = false }: { inherited?: boolean }) {
  const labels = useMonitorLabels()
  return <span className="execution-error-indicator" role="img" aria-label={labels.error}
    title={inherited ? labels.descendantError : labels.error}>!</span>
}

/** Error text stays local, is escaped by React and is revealed on demand. */
export function ExecutionError({ error, detail, identity }: { error?: string | null, detail?: ExecutionErrorDetail | null, identity: string }) {
  const labels = useMonitorLabels()
  const incident = readExecutionErrorDetail(detail)
  const [open, setOpen] = useState(false)
  const content = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    content.current?.closest('[role="dialog"]')?.querySelector<HTMLButtonElement>("button")?.focus()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [open])
  return <div className="execution-error">
    <Button variant="secondary" onClick={() => setOpen(true)}><ExecutionErrorIndicator />{labels.viewError}</Button>
    {open && createPortal(<div className="execution-error-modal" onKeyDown={(event) => {
      if (event.key === "Escape") {
        event.preventDefault()
        event.stopPropagation()
        setOpen(false)
      }
      if (event.key === "Tab") {
        const buttons = content.current?.closest('[role="dialog"]')?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")
        if (!buttons?.length) return
        const first = buttons[0]
        const last = buttons[buttons.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus()
        }
      }
    }}><Modal open label={labels.error} title={labels.error} onClose={() => setOpen(false)}>
      <div ref={content} className="execution-error-content">
        <p className="execution-error-context">{labels.errorContext}: {identity}</p>
        <dl className="execution-error-fields">
          <div><dt>{labels.affectedComponent}</dt><dd>
            {incident ? incident.agentId ?? labels.errorNotRecorded : identity}
            {incident?.invocationId && <span className="mono"> · #{incident.invocationId}</span>}
          </dd></div>
          <div><dt>{labels.incidentDate}</dt><dd>{incident?.occurredAt
            ? <time dateTime={incident.occurredAt}>{formatDateTime(incident.occurredAt)}</time> : labels.errorNotRecorded}</dd></div>
          <div><dt>{labels.errorType}</dt><dd>{incident
            ? <><code>{incident.code}</code>{incident.exceptionType && <span> · {incident.exceptionType}</span>}</>
            : labels.errorNotRecorded}</dd></div>
          <div><dt>{labels.recordedMessage}</dt><dd><pre className="execution-error-message">{incident?.message ?? error ?? labels.errorNotRecorded}</pre></dd></div>
        </dl>
        <div className="execution-error-footer"><Button variant="secondary" onClick={() => setOpen(false)}>{labels.dismiss}</Button></div>
      </div>
    </Modal></div>, document.body)}
  </div>
}

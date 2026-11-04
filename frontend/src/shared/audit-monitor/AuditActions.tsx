import { useContext, useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useTranslation } from "react-i18next"
import { Badge, Button, FolderIcon, Modal } from "../ui-kit/index.ts"
import { auditStateFrom, isFinished, type AuditStatusModel } from "./auditStatus.ts"
import { useAuditStateLabel, useMonitorLabels } from "./monitorLabels.ts"
import { cancelQualityAudit, type AuditCancellationResult } from "../../infrastructure/http-client/httpClient.ts"
import { AuditExecutionUpdateContext } from "../agent-monitor/useAgentExecutions.ts"
import "./AuditActions.css"
import { AuditCancelButton } from "./AuditCancelButton.tsx"

/** Requests cancellation; only a server outcome can mark a real audit finished. */
export function AuditActions({ audit }: { audit: AuditStatusModel }) {
  const { t } = useTranslation("projects")
  const labels = useMonitorLabels()
  const stateLabel = useAuditStateLabel()
  const updateAudit = useContext(AuditExecutionUpdateContext)
  const [open, setOpen] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(false)
  const [response, setResponse] = useState<AuditCancellationResult | null>(null)
  const inFlight = useRef(false)
  const content = useRef<HTMLDivElement>(null)
  const state = isFinished(audit.state) ? audit.state : response ? auditStateFrom(response.executionStatus, response.auditStatus) : audit.state
  const active = state === "running" || state === "waiting" || state === "cancelling"
  const pending = sending || state === "cancelling" || response !== null && active
  const eligible = audit.demo || audit.canCancel && (audit.project?.id ?? 0) > 0 && audit.id > 0
  const identity = t("auditStatus.title", { id: audit.id })

  async function confirmCancellation() {
    if (inFlight.current || pending || !active || !eligible) return
    if (audit.demo) { setOpen(false); return }
    inFlight.current = true
    setSending(true)
    setError(false)
    try {
      const result = await cancelQualityAudit(audit.project!.id, audit.id)
      updateAudit(result)
      setResponse(result)
    } catch {
      setError(true)
    } finally {
      inFlight.current = false
      setSending(false)
    }
  }

  useEffect(() => {
    if (!open || !active) return
    const previous = document.activeElement as HTMLElement | null
    const fallback = previous?.closest(".audit-disclosure")?.querySelector<HTMLButtonElement>(".audit-disclosure-toggle")
    content.current?.querySelector<HTMLButtonElement>("button")?.focus()
    return () => {
      if (previous?.isConnected && !previous.matches(":disabled")) previous.focus()
      else fallback?.focus()
    }
  }, [open, active])

  if (!active && open) setOpen(false)
  if (!active || !eligible) return null

  return <>
    <div className="audit-actions" role="group" aria-label={`${labels.actions} · ${identity}`}>
      {pending && <span className="audit-cancel-pending" role="status">{labels.cancelling}</span>}
      <AuditCancelButton pending={pending} onClick={() => setOpen(true)} />
    </div>
    {open && createPortal(
      <div className="audit-cancel-modal" onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault()
          event.stopPropagation()
          setOpen(false)
        }
        if (event.key === "Tab") {
          const dialog = content.current?.closest('[role="dialog"]')
          const buttons = dialog?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")
          if (!buttons?.length) return
          const first = buttons[0]
          const last = buttons[buttons.length - 1]
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault(); last.focus()
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault(); first.focus()
          }
        }
      }}>
        <Modal open label={labels.cancelTitle} title={labels.cancelTitle} size="narrow" onClose={() => setOpen(false)}>
          <div ref={content} className="audit-cancel-confirmation">
            <section className="audit-cancel-target" aria-label={labels.cancelTarget}>
              <span className="audit-cancel-label">{labels.cancelTarget}</span>
              <div className="audit-cancel-identity">
                <strong>{identity}</strong>
                <Badge tone="neutral">{stateLabel(pending ? "cancelling" : state)}</Badge>
              </div>
              {audit.project && <p className="audit-cancel-repository">
                <FolderIcon size={14} />
                <span className="mono">{audit.project.repositoryOwner}/{audit.project.repositoryName}</span>
              </p>}
            </section>
            <section className="audit-cancel-warning" aria-label={labels.cancelConsequences}>
              <h3>{labels.cancelConsequences}</h3>
              <p>{labels.cancelWarning}</p>
            </section>
            {audit.demo && <p className="audit-cancel-unavailable">{labels.cancelUnavailable}</p>}
            {pending && <p className="audit-cancel-unavailable" role="status">{labels.cancelRequested}</p>}
            {error && !pending && <p className="audit-cancel-error" role="alert">{labels.cancelError}</p>}
            <div className="audit-cancel-buttons">
              <Button variant="secondary" onClick={() => setOpen(false)}>{pending ? labels.dismiss : labels.keepRunning}</Button>
              <Button loading={sending} loadingText={labels.cancelling} disabled={pending}
                onClick={() => void confirmCancellation()}>{pending ? labels.cancelling : error ? labels.retryCancel : labels.confirmCancel}</Button>
            </div>
          </div>
        </Modal>
      </div>, document.body,
    )}
  </>
}

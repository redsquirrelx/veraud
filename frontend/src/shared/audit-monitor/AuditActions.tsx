import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useTranslation } from "react-i18next"
import { Badge, Button, FolderIcon, Modal } from "../ui-kit/index.ts"
import type { AuditStatusModel } from "./auditStatus.ts"
import { useMonitorLabels } from "./monitorLabels.ts"
import "./AuditActions.css"
import { AuditCancelButton } from "./AuditCancelButton.tsx"

/** Confirmation UI only: cancellation is not yet connected to the server. */
export function AuditActions({ audit }: { audit: AuditStatusModel }) {
  const { t } = useTranslation("projects")
  const labels = useMonitorLabels()
  const [open, setOpen] = useState(false)
  const content = useRef<HTMLDivElement>(null)
  const active = audit.state === "running" || audit.state === "waiting"
  const identity = t("auditStatus.title", { id: audit.id })

  useEffect(() => {
    if (!open || !active) return
    const previous = document.activeElement as HTMLElement | null
    content.current?.querySelector<HTMLButtonElement>("button")?.focus()
    return () => previous?.focus()
  }, [open, active])

  if (!active && open) setOpen(false)
  if (!active) return null

  return <>
    <div className="audit-actions" role="group" aria-label={`${labels.actions} · ${identity}`}>
      <AuditCancelButton onClick={() => setOpen(true)} />
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
                <Badge tone="neutral">{t(audit.state === "running" ? "auditStatus.states.running" : "auditStatus.states.waiting")}</Badge>
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
            <p className="audit-cancel-unavailable">{labels.cancelUnavailable}</p>
            <div className="audit-cancel-buttons">
              <Button variant="secondary" onClick={() => setOpen(false)}>{labels.keepRunning}</Button>
              <Button onClick={() => setOpen(false)}>{labels.confirmCancel}</Button>
            </div>
          </div>
        </Modal>
      </div>, document.body,
    )}
  </>
}

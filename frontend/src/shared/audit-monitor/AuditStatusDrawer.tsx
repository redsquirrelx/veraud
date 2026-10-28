import { useEffect, useId, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { ListIcon, XIcon } from "../ui-kit/index.ts"
import { AuditStatusDisclosure } from "./AuditStatusDisclosure.tsx"
import type { AuditStatusModel } from "./auditStatus.ts"
import "./AuditStatusDrawer.css"

export interface AuditStatusDrawerProps {
  audits: AuditStatusModel[]
}

/** Non-modal audit monitor: a tab on the left edge opens a panel that slides
 *  in from the right. It never traps focus or locks scrolling, so the view
 *  behind stays usable — unlike `Drawer`, which is deliberately modal. */
export function AuditStatusDrawer({ audits }: AuditStatusDrawerProps) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const panelId = useId()
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const wasOpen = useRef(false)
  const active = audits.some((audit) => audit.state === "running" || audit.state === "waiting")

  useEffect(() => {
    if (!open) {
      return
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault()
        setOpen(false)
      }
    }
    document.addEventListener("keydown", handleKey)
    return () => document.removeEventListener("keydown", handleKey)
  }, [open])

  // Moving focus into the panel on open and back to the tab on close keeps the
  // keyboard position next to what the user just revealed. Only on a real
  // transition, so mounting closed never steals focus from the page.
  useEffect(() => {
    if (open) {
      panel.current?.focus({ preventScroll: true })
    } else if (wasOpen.current) {
      trigger.current?.focus({ preventScroll: true })
    }
    wasOpen.current = open
  }, [open])

  return (
    <div className="audit-drawer">
      {/* One shell holds the tab and the panel, so the tab travels with the
          panel instead of staying behind at the viewport edge. */}
      <div className="audit-drawer-shell" data-open={open}>
        <button
          ref={trigger}
          type="button"
          className="audit-drawer-trigger"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((current) => !current)}
        >
          <ListIcon size={14} />
          <span className="audit-drawer-trigger-label">{t("auditStatus.drawer.trigger", { count: audits.length })}</span>
          {active && <span className="audit-drawer-trigger-active" aria-hidden="true" />}
        </button>
        <div
          ref={panel}
          id={panelId}
          className="audit-drawer-panel"
          role="region"
          aria-label={t("auditStatus.drawer.panelLabel")}
          aria-hidden={!open}
          inert={!open}
          tabIndex={-1}
        >
          <header className="audit-drawer-header">
            <h2>{t("auditStatus.drawer.title")}</h2>
            <button type="button" className="audit-drawer-close" aria-label={tCommon("ui.close")} onClick={() => setOpen(false)}>
              <XIcon size={16} />
            </button>
          </header>
          <div className="audit-drawer-body">
            {audits.length === 0 ? (
              <p className="label">{t("auditStatus.drawer.empty")}</p>
            ) : (
              audits.map((audit) => (
                // A finished audit has nothing left to watch, so it stays folded.
                <AuditStatusDisclosure key={audit.id} audit={audit} defaultExpanded={audit.state !== "completed"} evidenceLinks />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

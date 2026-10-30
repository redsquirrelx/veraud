import { useEffect, useId, useRef, useState, type CSSProperties } from "react"
import { useTranslation } from "react-i18next"
import { ListIcon, XIcon } from "../ui-kit/index.ts"
import { AuditStatusDisclosure } from "./AuditStatusDisclosure.tsx"
import { AuditMonitorLegend } from "./AuditMonitorLegend.tsx"
import { useMonitorLabels } from "./monitorLabels.ts"
import type { AuditStatusModel } from "./auditStatus.ts"
import "./AuditStatusDrawer.css"

export interface AuditStatusDrawerProps {
  audits: AuditStatusModel[]
}

const MIN_WIDTH = 420
const MAX_WIDTH = 560
const clampWidth = (width: number) => Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width))

/** Non-modal audit monitor: a tab on the left edge opens a panel that slides
 *  in from the right. It never traps focus or locks scrolling, so the view
 *  behind stays usable — unlike `Drawer`, which is deliberately modal. */
export function AuditStatusDrawer({ audits }: AuditStatusDrawerProps) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const labels = useMonitorLabels()
  const panelId = useId()
  const [open, setOpen] = useState(false)
  const [width, setWidth] = useState(MIN_WIDTH)
  const drag = useRef<{ pointerId: number, x: number, width: number } | null>(null)
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
    <div className="audit-drawer" style={{ "--audit-drawer-requested-width": `${width}px` } as CSSProperties}>
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
          <div className="audit-drawer-resize" role="separator" tabIndex={0} aria-orientation="vertical"
            aria-label={labels.resize} title={labels.resizeHint} aria-controls={panelId}
            aria-valuemin={MIN_WIDTH} aria-valuemax={MAX_WIDTH} aria-valuenow={width}
            onPointerDown={(event) => {
              if (event.button !== 0) return
              event.preventDefault()
              event.currentTarget.focus()
              event.currentTarget.setPointerCapture(event.pointerId)
              drag.current = { pointerId: event.pointerId, x: event.clientX, width }
            }}
            onPointerMove={(event) => {
              if (drag.current?.pointerId !== event.pointerId) return
              setWidth(clampWidth(drag.current.width + drag.current.x - event.clientX))
            }}
            onPointerUp={(event) => {
              if (drag.current?.pointerId !== event.pointerId) return
              drag.current = null
              event.currentTarget.releasePointerCapture(event.pointerId)
            }}
            onPointerCancel={() => { drag.current = null }}
            onLostPointerCapture={() => { drag.current = null }}
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
              event.preventDefault()
              setWidth((current) => clampWidth(event.key === "Home" ? MIN_WIDTH : event.key === "End" ? MAX_WIDTH
                : current + (event.key === "ArrowLeft" ? 20 : -20)))
            }} />
          <div className="audit-drawer-body">
            <AuditMonitorLegend />
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

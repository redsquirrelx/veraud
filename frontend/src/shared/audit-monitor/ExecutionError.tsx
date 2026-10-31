import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Button, Modal } from "../ui-kit/index.ts"
import { useMonitorLabels } from "./monitorLabels.ts"
import "./ExecutionError.css"

export function ExecutionErrorIndicator() {
  const labels = useMonitorLabels()
  return <span className="execution-error-indicator" role="img" aria-label={labels.error} title={labels.error}>!</span>
}

/** Error text stays local, is escaped by React and is revealed on demand. */
export function ExecutionError({ error }: { error: string }) {
  const labels = useMonitorLabels()
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
    {open && createPortal(<div onKeyDown={(event) => {
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
      <div ref={content}>
        <pre className="execution-error-message">{error}</pre>
        <Button variant="secondary" onClick={() => setOpen(false)}>{labels.dismiss}</Button>
      </div>
    </Modal></div>, document.body)}
  </div>
}

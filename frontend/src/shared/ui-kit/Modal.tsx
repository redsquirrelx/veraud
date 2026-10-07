import { useEffect, useRef, type MouseEvent, type ReactNode } from "react"
import { XIcon } from "./icons.tsx"
import "./Modal.css"

interface ModalProps {
  open: boolean
  label: string
  title?: string
  size?: "default" | "narrow"
  onClose: () => void
  children: ReactNode
}

export function Modal({ open, label, title, size = "default", onClose, children }: ModalProps) {
  const dialog = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose()
      }
    }
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("keydown", handleKey)
    }
  }, [open, onClose])

  if (!open) {
    return null
  }

  function handleOverlay(event: MouseEvent<HTMLDivElement>) {
    if (dialog.current !== null && !dialog.current.contains(event.target as Node)) {
      onClose()
    }
  }

  return (
    <div className="ui-modal-overlay" onMouseDown={handleOverlay}>
      <div className={size === "narrow" ? "ui-modal ui-modal-narrow" : "ui-modal"} role="dialog" aria-modal="true" aria-label={label} ref={dialog}>
        <div className="ui-modal-head">
          {title !== undefined && <span className="ui-modal-title">{title}</span>}
          <button type="button" className="ui-modal-close" aria-label="Close" onClick={onClose}>
            <XIcon size={14} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

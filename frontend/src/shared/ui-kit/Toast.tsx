import { useEffect, useRef, useState } from "react"
import "./Toast.css"

interface ToastProps {
  kind: "success" | "error"
  message: string
  durationMs?: number
  onClose?: () => void
}

const LONG_MESSAGE_CHARS = 120

export function Toast({ kind, message, durationMs = 5000, onClose }: ToastProps) {
  const [closing, setClosing] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const remaining = useRef(durationMs)
  const startedAt = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const long = message.length > LONG_MESSAGE_CHARS

  function clearTimer() {
    if (timer.current !== null) {
      clearTimeout(timer.current)
      timer.current = null
    }
  }

  function close() {
    if (closing) {
      return
    }
    clearTimer()
    if (onClose === undefined) {
      return
    }
    setClosing(true)
    setTimeout(() => onClose(), 200)
  }

  function startTimer() {
    if (onClose === undefined || closing) {
      return
    }
    startedAt.current = Date.now()
    timer.current = setTimeout(() => close(), remaining.current)
  }

  useEffect(() => {
    startTimer()
    return () => clearTimer()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleEnter() {
    if (timer.current === null) {
      return
    }
    clearTimer()
    remaining.current -= Date.now() - startedAt.current
  }

  function handleLeave() {
    if (remaining.current > 0) {
      startTimer()
    }
  }

  return (
    <div
      className={closing ? `ui-toast ui-toast-${kind} ui-toast-closing` : `ui-toast ui-toast-${kind}`}
      role={kind === "error" ? "alert" : "status"}
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      <span className={expanded ? "ui-toast-body" : "ui-toast-body ui-toast-clamped"}>{message}</span>
      {long && (
        <button
          type="button"
          className="ui-toast-toggle"
          aria-label={expanded ? "Show less" : "Show more"}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
      {onClose && (
        <button type="button" className="ui-toast-close" aria-label="Close" onClick={() => close()}>
          ├ù
        </button>
      )}
    </div>
  )
}

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import "./Tooltip.css"

interface TooltipProps {
  content: string
  disabled?: boolean
  placement?: "left" | "right"
  children: (props: { "aria-describedby"?: string }) => ReactNode
}

/** A non-interactive label placed beside its trigger, outside clipping containers. */
export function Tooltip({ content, disabled = false, placement = "right", children }: TooltipProps) {
  const id = useId()
  const trigger = useRef<HTMLSpanElement>(null)
  const bubble = useRef<HTMLSpanElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const exitTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [open, setOpen] = useState(false)
  const [closing, setClosing] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const visible = open && !disabled

  function cancelClose() { clearTimeout(timer.current) }
  const close = useCallback(() => {
    clearTimeout(timer.current)
    clearTimeout(exitTimer.current)
    setClosing(true)
    exitTimer.current = setTimeout(() => { setOpen(false); setClosing(false) }, 150)
  }, [])
  function show() {
    cancelClose()
    clearTimeout(exitTimer.current)
    setClosing(false)
    setOpen(true)
  }
  function scheduleClose() {
    cancelClose()
    timer.current = setTimeout(close, 100)
  }

  useEffect(() => () => { clearTimeout(timer.current); clearTimeout(exitTimer.current) }, [])
  useEffect(() => {
    if (!visible) return
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") close()
    }
    const hide = () => setOpen(false)
    document.addEventListener("keydown", dismiss)
    window.addEventListener("resize", hide)
    window.addEventListener("scroll", hide, true)
    return () => {
      document.removeEventListener("keydown", dismiss)
      window.removeEventListener("resize", hide)
      window.removeEventListener("scroll", hide, true)
    }
  }, [visible, close])

  useLayoutEffect(() => {
    if (!visible || !trigger.current || !bubble.current) return
    const anchor = trigger.current.getBoundingClientRect()
    const tooltip = bubble.current.getBoundingClientRect()
    setPosition({
      left: Math.max(8, Math.min(placement === "left" ? anchor.left - tooltip.width - 8 : anchor.right + 8, window.innerWidth - tooltip.width - 8)),
      top: Math.max(8, Math.min(anchor.top + (anchor.height - tooltip.height) / 2, window.innerHeight - tooltip.height - 8)),
    })
  }, [visible, content, placement])

  return <span ref={trigger} className="ui-tooltip-trigger"
    onMouseEnter={show} onMouseLeave={scheduleClose}
    onFocus={show} onBlur={close} onClick={close}>
    {children({ "aria-describedby": visible ? id : undefined })}
    {visible && createPortal(<span ref={bubble} id={id} role="tooltip" className="ui-tooltip" data-closing={closing}
      style={position} onMouseEnter={show} onMouseLeave={scheduleClose}>{content}</span>, document.body)}
  </span>
}

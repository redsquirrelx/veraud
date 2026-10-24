import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { useTranslation } from "react-i18next"
import { XIcon } from "./icons.tsx"
import { IconButton } from "./IconButton.tsx"
import "./Drawer.css"

export interface DrawerProps {
  open: boolean
  title: string
  description?: string
  size?: "default" | "wide"
  closeOnOverlay?: boolean
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}

/** Modal right-side panel with isolated scrolling and keyboard focus. */
export function Drawer({ open, title, description, size = "default", closeOnOverlay = true, onClose, children, footer }: DrawerProps) {
  const { t } = useTranslation("common")
  const id = useId()
  const [present, setPresent] = useState(open)
  // Mount before opening; keep the panel mounted until its exit finishes.
  if (open && !present) {
    setPresent(true)
  }
  const overlay = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLElement>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  const motion = useRef<{ panel: Animation, backdrop: Animation } | null>(null)
  const closeCallback = useRef(onClose)

  useEffect(() => { closeCallback.current = onClose }, [onClose])

  useLayoutEffect(() => {
    if (!present) return
    return () => {
      motion.current?.panel.cancel()
      motion.current?.backdrop.cancel()
      motion.current = null
    }
  }, [present])

  useLayoutEffect(() => {
    if (!present || !dialog.current || !backdrop.current || !overlay.current) return
    if (typeof dialog.current.animate !== "function") return

    // One timeline per mounted drawer. Reverse it rather than restarting at an
    // endpoint, including when the user closes before opening has finished.
    if (!motion.current) {
      overlay.current.dataset.motion = "native"
      const timing = { duration: 250, easing: "cubic-bezier(0.4, 0, 0.2, 1)", fill: "both" as const }
      const panelAnimation = dialog.current.animate([
        { transform: "translate3d(100%, 0, 0)" },
        { transform: "translate3d(0, 0, 0)" },
      ], timing)
      const backdropAnimation = backdrop.current.animate([{ opacity: 0 }, { opacity: 1 }], timing)
      panelAnimation.pause()
      backdropAnimation.pause()
      panelAnimation.currentTime = 0
      backdropAnimation.currentTime = 0
      panelAnimation.onfinish = () => {
        if (panelAnimation.playbackRate < 0) setPresent(false)
      }
      motion.current = { panel: panelAnimation, backdrop: backdropAnimation }
    }

    for (const animation of [motion.current.panel, motion.current.backdrop]) {
      animation.updatePlaybackRate(open ? 1 : -1)
      animation.play()
    }
  }, [open, present])

  useEffect(() => {
    if (open || !present) return
    // Fallback for environments that do not dispatch animationend.
    const timeout = window.setTimeout(() => setPresent(false), 300)
    return () => window.clearTimeout(timeout)
  }, [open, present])

  useEffect(() => {
    if (!present || !dialog.current || !overlay.current) return
    const panel = dialog.current
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    const background = Array.from(document.body.children)
      .filter((element) => element !== overlay.current)
      .map((element) => ({ element, inert: element.getAttribute("inert") }))

    document.body.style.overflow = "hidden"
    for (const { element } of background) element.setAttribute("inert", "")
    panel.querySelector<HTMLButtonElement>(".ui-drawer-close")?.focus({ preventScroll: true })

    function focusableElements() {
      return Array.from(panel.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]'))
        .filter((element) => {
          if (element.tabIndex < 0 || element.matches(":disabled") || element.closest("[hidden], [inert]")) return false
          for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
            const style = getComputedStyle(ancestor)
            if (style.display === "none" || style.visibility === "hidden") return false
            if (ancestor === panel) break
          }
          return true
        })
    }

    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault()
        closeCallback.current()
      } else if (event.key === "Tab") {
        const elements = focusableElements()
        const first = elements[0]
        const last = elements.at(-1)
        if (!first || !last) {
          event.preventDefault()
          panel.focus({ preventScroll: true })
        } else if (!panel.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
          event.preventDefault()
          const target = event.shiftKey ? last : first
          target.focus({ preventScroll: true })
        }
      }
    }

    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("keydown", handleKey)
      document.body.style.overflow = previousOverflow
      for (const { element, inert } of background) {
        if (inert === null) element.removeAttribute("inert")
        else element.setAttribute("inert", inert)
      }
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [present])

  if (!present) return null

  return createPortal(
    <div className="ui-drawer-overlay" data-state={open ? "open" : "closed"} ref={overlay} onClick={(event) => {
      if (open && closeOnOverlay && event.target === event.currentTarget) onClose()
    }}>
      <div className="ui-drawer-backdrop" ref={backdrop} aria-hidden="true" />
      <section
        ref={dialog}
        className={`ui-drawer ui-drawer-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={description ? `${id}-description` : undefined}
        tabIndex={-1}
        onAnimationEnd={(event) => {
          if (!open && !motion.current && event.target === event.currentTarget && event.animationName === "ui-drawer-slide-out") setPresent(false)
        }}
      >
        <header className="ui-drawer-header">
          <div className="ui-drawer-heading">
            <h2 id={`${id}-title`}>{title}</h2>
            {description && <p id={`${id}-description`}>{description}</p>}
          </div>
          <IconButton className="ui-drawer-close" variant="ghost" size="sm" ariaLabel={t("ui.close")} onClick={onClose}>
            <XIcon size={16} />
          </IconButton>
        </header>
        <div className="ui-drawer-body">{children}</div>
        {footer && <footer className="ui-drawer-footer">{footer}</footer>}
      </section>
    </div>,
    document.body,
  )
}

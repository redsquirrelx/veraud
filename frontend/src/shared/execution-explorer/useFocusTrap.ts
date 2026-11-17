import { useEffect, type RefObject } from "react"

/** Trap Tab/Shift+Tab within the panel, close on Escape and lock body scroll
 *  while active. Mirrors the Drawer's focus contract; kept local to the
 *  Execution Explorer so the shared modal and drawer stay untouched.
 *  Expects the overlay to be portaled to `document.body`, so every other body
 *  child is inerted while the explorer is open. */
export function useFocusTrap(dialogRef: RefObject<HTMLElement | null>, active: boolean, onClose: () => void) {
  useEffect(() => {
    if (!active || !dialogRef.current) return
    const panel = dialogRef.current
    const previousOverflow = document.body.style.overflow
    const background = Array.from(document.body.children)
      .filter((element) => !element.contains(panel))
      .map((element) => ({ element, inert: element.getAttribute("inert") }))

    document.body.style.overflow = "hidden"
    for (const { element } of background) element.setAttribute("inert", "")

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
        onClose()
        return
      }
      if (event.key !== "Tab") return
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

    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("keydown", handleKey)
      document.body.style.overflow = previousOverflow
      for (const { element, inert } of background) {
        if (inert === null) element.removeAttribute("inert")
        else element.setAttribute("inert", inert)
      }
    }
  }, [active, dialogRef, onClose])
}

import { useEffect, useId, useRef, useState, type KeyboardEvent, type FocusEvent } from "react"

interface Options {
  inactive: boolean
  initialSelector: string
  navigationSelector: string
}

export function useDropdownDisclosure({ inactive, initialSelector, navigationSelector }: Options) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const pendingFocus = useRef<"first" | "last" | null>(null)
  const expanded = open && !inactive

  function close(restoreFocus = false) {
    setOpen(false)
    if (restoreFocus) trigger.current?.focus()
  }

  function toggle() {
    setOpen(!expanded)
  }

  useEffect(() => {
    if (!expanded) return
    function outside(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", outside)
    if (pendingFocus.current) {
      const items = root.current?.querySelectorAll<HTMLElement>(initialSelector)
      const index = pendingFocus.current === "first" ? 0 : (items?.length ?? 0) - 1
      items?.[index]?.focus()
      pendingFocus.current = null
    }
    return () => document.removeEventListener("mousedown", outside)
  }, [expanded, initialSelector])

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && expanded) {
      event.preventDefault()
      close(true)
      return
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || inactive) return
    event.preventDefault()
    if (!expanded) {
      pendingFocus.current = event.key === "ArrowUp" || event.key === "End" ? "last" : "first"
      setOpen(true)
      return
    }
    const items = Array.from(root.current?.querySelectorAll<HTMLElement>(navigationSelector) ?? [])
    if (!items.length) return
    const current = items.indexOf(event.target as HTMLElement)
    const next = event.key === "Home" ? 0
      : event.key === "End" ? items.length - 1
        : current < 0 ? (event.key === "ArrowUp" ? items.length - 1 : 0)
          : (current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close()
  }

  return { id, root, trigger, expanded, close, toggle, onKeyDown, onBlur }
}

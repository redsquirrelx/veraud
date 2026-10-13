import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react"
import { CheckIcon, ChevronDownIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import "./DropdownMenu.css"

export interface DropdownMenuItem {
  id: string
  label: string
  description?: string
  disabled?: boolean
}

interface DropdownMenuProps {
  label: string
  items: DropdownMenuItem[]
  selectedId?: string | null
  onSelect: (id: string) => void
  icon?: ReactNode
  disabled?: boolean
  loading?: boolean
  loadingText?: string
  align?: "start" | "end"
  emptyText?: string
}

/** Action disclosure: buttons that report a selection, without a persistent value. */
export function DropdownMenu({ label, items, selectedId = null, onSelect, icon, disabled = false, loading = false, loadingText, align = "start", emptyText = "No options available" }: DropdownMenuProps) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const inactive = disabled || loading
  const expanded = open && !inactive
  const pendingFocus = useRef<"first" | "last" | null>(null)

  function close(restoreFocus = false) {
    setOpen(false)
    if (restoreFocus) trigger.current?.focus()
  }

  function choose(item: DropdownMenuItem) {
    close(true)
    onSelect(item.id)
  }

  useEffect(() => {
    if (!expanded) return
    function outside(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", outside)
    if (pendingFocus.current) {
      const buttons = root.current?.querySelectorAll<HTMLButtonElement>("[role='menuitem']")
      const index = pendingFocus.current === "first" ? 0 : (buttons?.length ?? 0) - 1
      buttons?.[index]?.focus()
      pendingFocus.current = null
    }
    return () => document.removeEventListener("mousedown", outside)
  }, [expanded])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
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
    const buttons = Array.from(root.current?.querySelectorAll<HTMLButtonElement>("[role='menuitem']:not(:disabled)") ?? [])
    if (!buttons.length) return
    const current = buttons.indexOf(event.target as HTMLButtonElement)
    const next = event.key === "Home" ? 0
      : event.key === "End" ? buttons.length - 1
        : current < 0 ? (event.key === "ArrowUp" ? buttons.length - 1 : 0)
          : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length
    buttons[next]?.focus()
  }

  return (
    <div className="ui-dropdown-menu" ref={root} onKeyDown={handleKeyDown} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close()
    }}>
      <button
        id={`${id}-trigger`}
        ref={trigger}
        type="button"
        className="ui-dropdown-menu-trigger"
        disabled={inactive}
        aria-expanded={expanded}
        aria-haspopup="menu"
        aria-label={loading && loadingText !== undefined ? loadingText : label}
        title={label}
        aria-controls={`${id}-menu`}
        onClick={() => setOpen(!expanded)}
      >
        {loading && loadingText === undefined && <Spinner size={12} tone="dark" />}
        {icon && !loading && <span aria-hidden="true">{icon}</span>}
        <span>{loading && loadingText !== undefined ? loadingText : label}</span>
        <span className="ui-dropdown-menu-chevron" data-open={expanded} aria-hidden="true"><ChevronDownIcon /></span>
      </button>
      {expanded && (
        <div id={`${id}-menu`} className="ui-dropdown-menu-panel" data-align={align} role="menu" aria-labelledby={`${id}-trigger`}>
          {items.length === 0 ? <p className="ui-dropdown-menu-empty">{emptyText}</p> : (
            <ul>
              {items.map((item) => {
                const selected = item.id === selectedId
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      role="menuitem"
                      className="ui-dropdown-menu-item"
                      disabled={item.disabled}
                      aria-current={selected || undefined}
                      onClick={() => choose(item)}
                    >
                      <span className="ui-dropdown-menu-text">
                        <span>{item.label}</span>
                        {item.description && <span className="ui-dropdown-menu-description">{item.description}</span>}
                      </span>
                      {selected && <span aria-hidden="true"><CheckIcon size={14} /></span>}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

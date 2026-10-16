import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ChevronDownIcon, ExternalIcon } from "./icons.tsx"
import "./DropdownLinks.css"

export interface DropdownLinkItem {
  label: string
  href: string
  description?: string
  external?: boolean
  disabled?: boolean
}

interface DropdownLinksProps {
  label: string
  items: DropdownLinkItem[]
  icon?: ReactNode
  disabled?: boolean
  align?: "start" | "end"
  emptyText?: string
  iconOnly?: boolean
}

/** Navigation disclosure: real links, without a persistent selected value. */
export function DropdownLinks({ label, items, icon, disabled = false, align = "start", emptyText, iconOnly = false }: DropdownLinksProps) {
  const { t } = useTranslation("common")
  const resolvedEmptyText = emptyText ?? t("ui.dropdownLinks.noLinks")
  const id = useId()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const expanded = open && !disabled
  const pendingFocus = useRef<"first" | "last" | null>(null)

  function close(restoreFocus = false) {
    setOpen(false)
    if (restoreFocus) trigger.current?.focus()
  }

  useEffect(() => {
    if (!expanded) return
    function outside(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", outside)
    if (pendingFocus.current) {
      const links = root.current?.querySelectorAll<HTMLAnchorElement>("a")
      const index = pendingFocus.current === "first" ? 0 : (links?.length ?? 0) - 1
      links?.[index]?.focus()
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
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) || disabled) return
    event.preventDefault()
    if (!expanded) {
      pendingFocus.current = event.key === "ArrowUp" || event.key === "End" ? "last" : "first"
      setOpen(true)
      return
    }
    const links = Array.from(root.current?.querySelectorAll<HTMLAnchorElement>("a") ?? [])
    if (!links.length) return
    const current = links.indexOf(event.target as HTMLAnchorElement)
    const next = event.key === "Home" ? 0
      : event.key === "End" ? links.length - 1
        : current < 0 ? (event.key === "ArrowUp" ? links.length - 1 : 0)
          : (current + (event.key === "ArrowDown" ? 1 : -1) + links.length) % links.length
    links[next]?.focus()
  }

  return (
    <div className="ui-dropdown-links" ref={root} onKeyDown={handleKeyDown} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) close()
    }}>
      <button
        id={`${id}-trigger`}
        ref={trigger}
        type="button"
        className="ui-dropdown-links-trigger"
        disabled={disabled}
        aria-expanded={expanded}
        aria-label={label}
        title={label}
        aria-controls={`${id}-links`}
        onClick={() => setOpen(!expanded)}
      >
        {icon && <span aria-hidden="true">{icon}</span>}
        {!iconOnly && <span>{label}</span>}
        {!iconOnly && <span className="ui-dropdown-links-chevron" data-open={expanded} aria-hidden="true"><ChevronDownIcon /></span>}
      </button>
      {expanded && (
        <nav id={`${id}-links`} className="ui-dropdown-links-panel" data-align={align} aria-labelledby={`${id}-trigger`}>
          {items.length === 0 ? <p className="ui-dropdown-links-empty">{resolvedEmptyText}</p> : (
            <ul>
              {items.map((item) => {
                const content = <>
                  <span className="ui-dropdown-links-text">
                    <span>{item.label}</span>
                    {item.description && <span className="ui-dropdown-links-description">{item.description}</span>}
                  </span>
                  {item.external && <span aria-hidden="true"><ExternalIcon size={14} /></span>}
                </>
                return (
                  <li key={item.href}>
                    {item.disabled ? (
                      <span className="ui-dropdown-links-item" aria-disabled="true">{content}</span>
                    ) : item.external ? (
                      <a className="ui-dropdown-links-item" href={item.href} target="_blank" rel="noopener noreferrer" aria-label={t("ui.dropdownLinks.newTab", { label: item.label })} onClick={() => close(true)}>{content}</a>
                    ) : (
                      <Link className="ui-dropdown-links-item" to={item.href} onClick={() => close(true)}>{content}</Link>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </nav>
      )}
    </div>
  )
}

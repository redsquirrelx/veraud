import { useState, type ReactNode } from "react"
import { ChevronLeftIcon, ChevronRightIcon } from "./icons.tsx"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import "./Sidebar.css"

export interface SidebarItem {
  id: string
  label: string
  icon?: ReactNode
}

interface SidebarProps {
  title: string
  items: SidebarItem[]
  activeId?: string
  defaultExpanded?: boolean
  storageKey?: string
  onSelect?: (id: string) => void
}

export function Sidebar({ title, items, activeId, defaultExpanded = true, storageKey, onSelect }: SidebarProps) {
  const [expanded, setExpanded] = useState(() =>
    storageKey === undefined ? defaultExpanded : localStorage.get(storageKey, defaultExpanded)
  )

  function toggle() {
    const next = !expanded
    setExpanded(next)
    if (storageKey !== undefined) {
      localStorage.set(storageKey, next)
    }
  }

  return (
    <aside className={expanded ? "ui-sidebar" : "ui-sidebar ui-sidebar-collapsed"} aria-label={title}>
      <div className="ui-sidebar-top">
        {expanded && <span className="ui-sidebar-title">{title}</span>}
        <button
          type="button"
          className="ui-sidebar-toggle"
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          aria-expanded={expanded}
          onClick={() => toggle()}
        >
          {expanded ? <ChevronLeftIcon /> : <ChevronRightIcon />}
        </button>
      </div>
      <nav className="ui-sidebar-nav">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === activeId ? "ui-sidebar-item ui-sidebar-item-active" : "ui-sidebar-item"}
            title={item.label}
            onClick={() => onSelect?.(item.id)}
          >
            {item.icon && <span className="ui-sidebar-icon">{item.icon}</span>}
            {expanded && <span>{item.label}</span>}
          </button>
        ))}
      </nav>
    </aside>
  )
}

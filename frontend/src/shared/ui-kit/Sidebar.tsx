import { useLayoutEffect, useRef, useState, type ReactNode } from "react"
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
  header?: (expanded: boolean) => ReactNode
  beforeItems?: (expanded: boolean) => ReactNode
  footer?: (expanded: boolean) => ReactNode
}

export function Sidebar({ title, items, activeId, defaultExpanded = true, storageKey, onSelect, header, beforeItems, footer }: SidebarProps) {
  const root = useRef<HTMLElement>(null)
  const previousSize = useRef<{ width: number, height: number, padding: string } | null>(null)
  const [expanded, setExpanded] = useState(() => {
    const stored = storageKey === undefined ? defaultExpanded : localStorage.get<unknown>(storageKey, defaultExpanded)
    return typeof stored === "boolean" ? stored : defaultExpanded
  })

  useLayoutEffect(() => {
    const previous = previousSize.current
    previousSize.current = null
    const element = root.current
    if (!previous || !element) return
    const next = element.getBoundingClientRect()
    const padding = getComputedStyle(element).padding
    // Animate explicit dimensions like the Drawer; interrupted toggles start
    // from the currently displayed size rather than jumping to an endpoint.
    const changesWidth = Math.abs(previous.width - next.width) > 1
    const from = changesWidth ? { width: `${previous.width}px` } : { height: `${previous.height}px` }
    const to = changesWidth ? { width: `${next.width}px` } : { height: `${next.height}px` }
    const animation = element.animate?.([
      { ...from, padding: previous.padding },
      { ...to, padding },
    ], { duration: 250, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" })
    const contentAnimations = expanded ? Array.from(element.querySelectorAll<HTMLElement>(".ui-sidebar-top, .ui-sidebar-nav, .ui-sidebar-footer"))
      .map((content) => content.animate?.([
        { opacity: 0, transform: "translateX(-6px)" },
        { opacity: 1, transform: "translateX(0)" },
      ], { duration: 200, easing: "ease-out" })) : []
    return () => {
      animation?.cancel()
      contentAnimations.forEach((contentAnimation) => contentAnimation?.cancel())
    }
  }, [expanded])

  function toggle() {
    if (root.current) {
      const { width, height } = root.current.getBoundingClientRect()
      previousSize.current = { width, height, padding: getComputedStyle(root.current).padding }
    }
    const next = !expanded
    setExpanded(next)
    if (storageKey !== undefined) {
      localStorage.set(storageKey, next)
    }
  }

  return (
    <aside ref={root} className={expanded ? "ui-sidebar" : "ui-sidebar ui-sidebar-collapsed"} aria-label={title}>
      <div className="ui-sidebar-top">
        {header ? header(expanded) : expanded && <span className="ui-sidebar-title">{title}</span>}
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
      {beforeItems?.(expanded)}
      <nav className="ui-sidebar-nav" aria-label={`${title} sections`}>
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === activeId ? "ui-sidebar-item ui-sidebar-item-active" : "ui-sidebar-item"}
             title={item.label}
             aria-label={item.label}
             aria-current={item.id === activeId ? "page" : undefined}
            onClick={() => onSelect?.(item.id)}
          >
            {item.icon && <span className="ui-sidebar-icon">{item.icon}</span>}
            {expanded && <span>{item.label}</span>}
          </button>
        ))}
      </nav>
      {footer && <div className="ui-sidebar-footer">{footer(expanded)}</div>}
    </aside>
  )
}

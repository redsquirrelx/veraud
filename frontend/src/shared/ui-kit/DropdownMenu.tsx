import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { CheckIcon, ChevronDownIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import { useDropdownDisclosure } from "./useDropdownDisclosure.ts"
import "./MenuSurface.css"
import "./Dropdown.css"

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
export function DropdownMenu({ label, items, selectedId = null, onSelect, icon, disabled = false, loading = false, loadingText, align = "start", emptyText }: DropdownMenuProps) {
  const { t } = useTranslation("common")
  const resolvedEmptyText = emptyText ?? t("ui.dropdownMenu.noOptions")
  const inactive = disabled || loading
  const { id, root, trigger, expanded, close, toggle, onKeyDown, onBlur } = useDropdownDisclosure({
    inactive,
    initialSelector: "[role='menuitem']",
    navigationSelector: "[role='menuitem']:not(:disabled)",
  })

  function choose(item: DropdownMenuItem) {
    close(true)
    onSelect(item.id)
  }

  return (
    <div className="ui-dropdown-menu" ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
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
        onClick={toggle}
      >
        {loading && loadingText === undefined && <Spinner size={12} tone="dark" />}
        {icon && !loading && <span aria-hidden="true">{icon}</span>}
        <span>{loading && loadingText !== undefined ? loadingText : label}</span>
        <span className="ui-dropdown-menu-chevron" data-open={expanded} aria-hidden="true"><ChevronDownIcon /></span>
      </button>
      {expanded && (
        <div id={`${id}-menu`} className="ui-dropdown-menu-panel ui-menu-surface" data-align={align} role="menu" aria-labelledby={`${id}-trigger`}>
          {items.length === 0 ? <p className="ui-dropdown-menu-empty">{resolvedEmptyText}</p> : (
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

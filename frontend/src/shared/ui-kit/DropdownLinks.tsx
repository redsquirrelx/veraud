import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ChevronDownIcon, ExternalIcon } from "./icons.tsx"
import { useDropdownDisclosure } from "./useDropdownDisclosure.ts"
import "./MenuSurface.css"
import "./Dropdown.css"

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
  const { id, root, trigger, expanded, close, toggle, onKeyDown, onBlur } = useDropdownDisclosure({
    inactive: disabled,
    initialSelector: "a",
    navigationSelector: "a",
  })

  return (
    <div className="ui-dropdown-links" ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
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
        onClick={toggle}
      >
        {icon && <span aria-hidden="true">{icon}</span>}
        {!iconOnly && <span>{label}</span>}
        {!iconOnly && <span className="ui-dropdown-links-chevron" data-open={expanded} aria-hidden="true"><ChevronDownIcon /></span>}
      </button>
      {expanded && (
        <nav id={`${id}-links`} className="ui-dropdown-links-panel ui-menu-surface" data-align={align} aria-labelledby={`${id}-trigger`}>
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

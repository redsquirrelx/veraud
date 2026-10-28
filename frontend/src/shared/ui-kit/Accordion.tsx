import { useId, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { ChevronDownIcon } from "./icons.tsx"
import "./Accordion.css"

export interface AccordionProps {
  title: string
  open: boolean
  onOpenChange: (open: boolean) => void
  disabled?: boolean
  headerAction?: ReactNode
  children: ReactNode
}

/** Controlled disclosure with independent, always-visible header actions. */
export function Accordion({ title, open, onOpenChange, disabled = false, headerAction, children }: AccordionProps) {
  const { t } = useTranslation("common")
  const id = useId()
  const expanded = open && !disabled

  return <section className="ui-accordion" data-open={expanded}>
    <div className="ui-accordion-header">
      <h3 className="ui-accordion-heading" aria-label={title}>
        <button type="button" id={`${id}-trigger`} className="ui-accordion-trigger"
          disabled={disabled} aria-expanded={expanded} aria-controls={`${id}-content`}
          aria-label={t(expanded ? "ui.accordion.collapse" : "ui.accordion.expand", { title })}
          onClick={() => onOpenChange(!expanded)}>
          <ChevronDownIcon size={16} />
          <span>{title}</span>
        </button>
      </h3>
      {headerAction && <div className="ui-accordion-action">{headerAction}</div>}
    </div>
    <div id={`${id}-content`} className="ui-accordion-content" hidden={!expanded}>
      {children}
    </div>
  </section>
}

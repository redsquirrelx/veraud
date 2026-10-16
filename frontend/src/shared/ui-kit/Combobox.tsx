import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react"
import { useTranslation } from "react-i18next"
import { ChevronDownIcon } from "./icons.tsx"
import "./FormControls.css"

export interface ComboboxOption {
  value: string
  label: string
  disabled?: boolean
}

interface ComboboxProps {
  label: string
  value: string
  options: ComboboxOption[]
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  error?: string
  description?: string
  name?: string
}

export function Combobox({ label, value, options, onChange, placeholder, disabled = false, error, description, name }: ComboboxProps) {
  const { t } = useTranslation("common")
  const resolvedPlaceholder = placeholder ?? t("ui.combobox.selectOption")
  const id = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const search = useRef("")
  const lastKey = useRef(0)
  const selected = options.find((option) => option.value === value)
  const message = error || description
  const expanded = open && !disabled

  useEffect(() => {
    if (!expanded) return
    function outside(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", outside)
    return () => document.removeEventListener("mousedown", outside)
  }, [expanded])

  useEffect(() => {
    if (expanded && active >= 0) {
      document.getElementById(`${id}-option-${active}`)?.scrollIntoView?.({ block: "nearest" })
    }
  }, [expanded, active, id])

  function show() {
    const index = options.findIndex((option) => option.value === value && !option.disabled)
    setActive(index >= 0 ? index : options.findIndex((option) => !option.disabled))
    setOpen(true)
  }

  function pick(index: number) {
    const option = options[index]
    if (option === undefined || option.disabled) return
    onChange(option.value)
    setOpen(false)
    trigger.current?.focus()
  }

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false)
      if (event.key === "Escape" && expanded) event.preventDefault()
      return
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      if (expanded) pick(active)
      else show()
      return
    }
    const enabled = options.map((option, index) => option.disabled ? -1 : index).filter((index) => index >= 0)
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault()
      if (!expanded) { show(); return }
      const position = enabled.indexOf(active)
      const next = event.key === "Home" ? 0 : event.key === "End" ? enabled.length - 1 : (position + (event.key === "ArrowDown" ? 1 : -1) + enabled.length) % enabled.length
      setActive(enabled[next] ?? -1)
    } else if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
      event.preventDefault()
      const now = Date.now()
      search.current = now - lastKey.current > 700 ? event.key : search.current + event.key
      lastKey.current = now
      const match = enabled.find((index) => options[index]?.label.toLowerCase().startsWith(search.current.toLowerCase()))
      setOpen(true)
      if (match !== undefined) setActive(match)
    }
  }

  return (
    <div className="ui-combobox" ref={root} data-invalid={Boolean(error)}>
      <span id={`${id}-label`} className="ui-control-label">{label}</span>
      {name && <input type="hidden" name={name} value={value} disabled={disabled} />}
      <button ref={trigger} type="button" role="combobox" className="ui-combobox-trigger" aria-labelledby={`${id}-label`} aria-expanded={expanded} aria-controls={`${id}-list`} aria-haspopup="listbox" aria-activedescendant={expanded && active >= 0 ? `${id}-option-${active}` : undefined} aria-invalid={Boolean(error)} aria-describedby={message ? `${id}-message` : undefined} disabled={disabled} onKeyDown={keyDown} onBlur={(event) => { if (!root.current?.contains(event.relatedTarget as Node | null)) setOpen(false) }} onClick={() => expanded ? setOpen(false) : show()}>
        <span className={selected ? "" : "ui-control-description"}>{selected?.label ?? resolvedPlaceholder}</span>
        <span className="ui-combobox-chevron" data-open={expanded}><ChevronDownIcon /></span>
      </button>
      <ul id={`${id}-list`} role="listbox" aria-labelledby={`${id}-label`} className="ui-combobox-menu" data-open={expanded} aria-hidden={!expanded} inert={!expanded}>
        {options.length === 0 && <li className="ui-combobox-empty">{t("ui.combobox.noOptions")}</li>}
        {options.map((option, index) => (
          <li key={option.value} id={`${id}-option-${index}`} role="option" aria-selected={option.value === value} aria-disabled={Boolean(option.disabled)} className="ui-combobox-option" data-active={active === index} onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => { if (!option.disabled) setActive(index) }} onClick={() => pick(index)}>
            <span>{option.label}</span><span aria-hidden="true">{option.value === value ? "Γ£ô" : ""}</span>
          </li>
        ))}
      </ul>
      {message && <span id={`${id}-message`} className={error ? "ui-control-error" : "ui-control-description"}>{message}</span>}
    </div>
  )
}

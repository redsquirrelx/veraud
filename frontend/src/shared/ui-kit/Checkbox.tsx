import { useEffect, useId, useRef } from "react"
import "./FormControls.css"

interface CheckboxProps {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  indeterminate?: boolean
  disabled?: boolean
  error?: string
  description?: string
  name?: string
}

export function Checkbox({ label, checked, onChange, indeterminate = false, disabled = false, error, description, name }: CheckboxProps) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const message = error || description

  useEffect(() => {
    if (input.current !== null) input.current.indeterminate = indeterminate
  }, [indeterminate])

  return (
    <label className="ui-choice" data-disabled={disabled} data-invalid={Boolean(error)}>
      <span className="ui-choice-control">
        <input ref={input} type="checkbox" name={name} checked={checked} disabled={disabled} aria-labelledby={`${id}-label`} aria-invalid={Boolean(error)} aria-describedby={message ? id : undefined} onChange={(event) => onChange(event.target.checked)} />
        <span className="ui-checkbox-mark" aria-hidden="true">
          <svg viewBox="0 0 16 16"><path d={indeterminate ? "M4 8h8" : "m4 8 3 3 5-6"} /></svg>
        </span>
      </span>
      <span className="ui-choice-copy">
        <span id={`${id}-label`}>{label}</span>
        {message && <span id={id} className={error ? "ui-control-error" : "ui-control-description"}>{message}</span>}
      </span>
    </label>
  )
}

import { useId } from "react"
import "./FormControls.css"

interface RadioButtonProps {
  label: string
  name: string
  value: string
  checked: boolean
  onChange: (value: string) => void
  disabled?: boolean
  error?: string
  description?: string
}

export function RadioButton({ label, name, value, checked, onChange, disabled = false, error, description }: RadioButtonProps) {
  const id = useId()
  const message = error || description

  return (
    <label className="ui-choice" data-disabled={disabled} data-invalid={Boolean(error)}>
      <span className="ui-choice-control">
        <input type="radio" name={name} value={value} checked={checked} disabled={disabled} aria-invalid={Boolean(error)} aria-describedby={message ? id : undefined} onChange={() => onChange(value)} />
        <span className="ui-radio-mark" aria-hidden="true" />
      </span>
      <span className="ui-choice-copy">
        <span>{label}</span>
        {message && <span id={id} className={error ? "ui-control-error" : "ui-control-description"}>{message}</span>}
      </span>
    </label>
  )
}

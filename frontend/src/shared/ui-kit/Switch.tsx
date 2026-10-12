import { useId } from "react"
import "./FormControls.css"

interface SwitchProps {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  error?: string
  description?: string
  name?: string
}

export function Switch({ label, checked, onChange, disabled = false, error, description, name }: SwitchProps) {
  const id = useId()
  const message = error || description

  return (
    <label className="ui-choice" data-disabled={disabled} data-invalid={Boolean(error)}>
      <span className="ui-choice-control ui-switch-control">
        <input type="checkbox" role="switch" name={name} checked={checked} disabled={disabled} aria-invalid={Boolean(error)} aria-describedby={message ? id : undefined} onChange={(event) => onChange(event.target.checked)} />
        <span className="ui-switch-track" aria-hidden="true"><span className="ui-switch-thumb" /></span>
      </span>
      <span className="ui-choice-copy">
        <span>{label}</span>
        {message && <span id={id} className={error ? "ui-control-error" : "ui-control-description"}>{message}</span>}
      </span>
    </label>
  )
}

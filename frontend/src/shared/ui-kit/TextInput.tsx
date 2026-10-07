import "./TextInput.css"

interface TextInputProps {
  value: string
  placeholder?: string
  label?: string
  type?: "text" | "password"
  disabled?: boolean
  onChange: (value: string) => void
}

export function TextInput({ value, placeholder, label = "", type = "text", disabled = false, onChange }: TextInputProps) {
  if (label === "") {
    return (
      <input
        type={type}
        className="ui-input"
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }

  return (
    <div className="ui-text-input">
      <span className="ui-item-legend">{label}</span>
      <input
        type={type}
        className="ui-input"
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

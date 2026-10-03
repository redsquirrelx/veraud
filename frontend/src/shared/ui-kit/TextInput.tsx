import "./TextInput.css"

interface TextInputProps {
  value: string
  placeholder?: string
  disabled?: boolean
  onChange: (value: string) => void
}

export function TextInput({ value, placeholder, disabled = false, onChange }: TextInputProps) {
  return (
    <input
      type="text"
      className="ui-input"
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

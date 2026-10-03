import type { ReactNode } from "react"
import { Spinner } from "./Spinner.tsx"
import "./Button.css"

interface ButtonProps {
  children: ReactNode
  disabled?: boolean
  loading?: boolean
  loadingText?: string
  variant?: "primary" | "secondary"
  title?: string
  onClick?: () => void
  type?: "button" | "submit"
}

export function Button({ children, disabled = false, loading = false, loadingText, variant = "primary", title, onClick, type = "button" }: ButtonProps) {
  const isDisabled = disabled || loading

  return (
    <button type={type} className={`ui-button ui-button-${variant}`} disabled={isDisabled} title={title} onClick={onClick}>
      {loading && loadingText === undefined && <Spinner size={12} tone={variant === "primary" ? "light" : "dark"} />}
      <span>{loading && loadingText !== undefined ? loadingText : children}</span>
    </button>
  )
}

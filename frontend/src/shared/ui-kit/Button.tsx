import type { ReactNode } from "react"
import { Spinner } from "./Spinner.tsx"
import "./Button.css"

interface ButtonProps {
  children: ReactNode
  disabled?: boolean
  loading?: boolean
  loadingText?: string
  variant?: "primary" | "secondary"
  square?: boolean
  title?: string
  ariaLabel?: string
  onClick?: () => void
  type?: "button" | "submit"
}

export function Button({ children, disabled = false, loading = false, loadingText, variant = "primary", square = false, title, ariaLabel, onClick, type = "button" }: ButtonProps) {
  const isDisabled = disabled || loading
  const shape = square ? " ui-button-square" : ""

  return (
    <button type={type} className={`ui-button ui-button-${variant}${shape}`} disabled={isDisabled} title={title} aria-label={ariaLabel} onClick={onClick}>
      {loading && loadingText === undefined && <Spinner size={12} tone={variant === "primary" ? "light" : "dark"} />}
      <span>{loading && loadingText !== undefined ? loadingText : children}</span>
    </button>
  )
}

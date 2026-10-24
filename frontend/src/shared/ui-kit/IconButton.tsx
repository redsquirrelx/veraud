import type { ComponentPropsWithRef, ReactNode } from "react"
import "./IconButton.css"

type NativeButtonProps = Omit<ComponentPropsWithRef<"button">, "children" | "aria-label" | "type">

interface IconButtonProps extends NativeButtonProps {
  children: ReactNode
  ariaLabel: string
  size?: "sm" | "md"
  variant?: "ghost" | "outline" | "pagination"
  type?: "button" | "submit" | "reset"
}

export function IconButton({ children, ariaLabel, size = "md", variant = "outline", type = "button", className, ...props }: IconButtonProps) {
  const classes = ["ui-icon-button", `ui-icon-button-${variant}`, `ui-icon-button-${size}`, className].filter(Boolean).join(" ")
  return <button {...props} type={type} className={classes} aria-label={ariaLabel}>{children}</button>
}

import type { ReactNode } from "react"
import "./Badge.css"

interface BadgeProps {
  tone: "success" | "warning" | "info" | "neutral" | "danger" | "unknown"
  children: ReactNode
  dot?: boolean
  compact?: boolean
  highlighted?: boolean
  title?: string
  "aria-label"?: string
}

export function Badge({ tone, children, dot = false, compact = false, highlighted, title, "aria-label": ariaLabel }: BadgeProps) {
  const classes = [
    "ui-badge", `ui-badge-${tone}`,
    dot && "ui-badge-with-dot",
    compact && "ui-badge-compact",
    highlighted !== undefined && "ui-badge-highlightable",
    highlighted && "ui-badge-highlighted",
  ].filter(Boolean).join(" ")
  return <span className={classes} title={title} aria-label={ariaLabel}>
    {dot && <span className="ui-badge-dot" aria-hidden="true" />}
    <span className="ui-badge-content">{children}</span>
  </span>
}

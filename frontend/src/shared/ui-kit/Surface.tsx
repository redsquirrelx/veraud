import type { ReactNode } from "react"
import "./Surface.css"

export type SurfaceLayout = "plain" | "stack"
export type SurfaceGap = "sm" | "md" | "lg" | "xl"
export type SurfaceAlign = "start" | "stretch"
export type SurfacePadding = "default" | "responsive"
export type SurfaceTone = "card" | "tinted" | "subtle"

interface SurfaceProps {
  asClass: "ui-card" | "ui-panel"
  tone: SurfaceTone
  children: ReactNode
  className?: string
  layout?: SurfaceLayout
  gap?: SurfaceGap
  align?: SurfaceAlign
  padding?: SurfacePadding
}

export function Surface({ asClass, tone, children, className, layout = "plain", gap = "sm", align = "start", padding = "default" }: SurfaceProps) {
  const classes = [
    "ui-surface", `ui-surface-${tone}`, asClass,
    layout === "stack" && "ui-surface-stack",
    `ui-surface-gap-${gap}`,
    `ui-surface-align-${align}`,
    `ui-surface-padding-${padding}`,
    className,
  ].filter(Boolean).join(" ")
  return <div className={classes}>{children}</div>
}

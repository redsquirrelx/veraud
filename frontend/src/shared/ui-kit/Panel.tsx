import type { ReactNode } from "react"
import { Surface, type SurfaceAlign, type SurfaceGap, type SurfaceLayout, type SurfacePadding, type SurfaceTone } from "./Surface.tsx"

interface PanelProps {
  children: ReactNode
  className?: string
  layout?: SurfaceLayout
  gap?: SurfaceGap
  align?: SurfaceAlign
  padding?: SurfacePadding
  tone?: Exclude<SurfaceTone, "card">
}

export function Panel({ children, tone = "tinted", ...props }: PanelProps) {
  return <Surface asClass="ui-panel" tone={tone} {...props}>{children}</Surface>
}

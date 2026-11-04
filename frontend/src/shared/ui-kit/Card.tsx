import type { ReactNode } from "react"
import { Surface, type SurfaceAlign, type SurfaceGap, type SurfaceLayout, type SurfacePadding } from "./Surface.tsx"

interface CardProps {
  children: ReactNode
  className?: string
  layout?: SurfaceLayout
  gap?: SurfaceGap
  align?: SurfaceAlign
  padding?: SurfacePadding
}

export function Card({ children, ...props }: CardProps) {
  return <Surface asClass="ui-card" tone="card" {...props}>{children}</Surface>
}

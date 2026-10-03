import type { ReactNode } from "react"
import "./Panel.css"

interface PanelProps {
  children: ReactNode
}

export function Panel({ children }: PanelProps) {
  return <div className="ui-panel">{children}</div>
}

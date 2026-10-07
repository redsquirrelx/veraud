import { useRef, useState, type ReactNode } from "react"
import "./SplitView.css"

interface SplitViewProps {
  left: ReactNode
  right: ReactNode
  initialRatio?: number
  minRatio?: number
  label?: string
}

function clampRatio(value: number, minRatio: number): number {
  if (value < minRatio) {
    return minRatio
  }
  if (value > 1 - minRatio) {
    return 1 - minRatio
  }
  return value
}

export function SplitView({ left, right, initialRatio = 0.5, minRatio = 0.2, label = "Resize panes" }: SplitViewProps) {
  const [ratio, setRatio] = useState(() => clampRatio(initialRatio, minRatio))
  const root = useRef<HTMLDivElement | null>(null)
  const dragging = useRef(false)

  function ratioFromClientX(clientX: number): number {
    const rect = root.current?.getBoundingClientRect()
    if (rect === undefined || rect.width === 0) {
      return ratio
    }
    return clampRatio((clientX - rect.left) / rect.width, minRatio)
  }

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return
    }
    dragging.current = true
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setRatio(ratioFromClientX(event.clientX))
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragging.current) {
      return
    }
    setRatio(ratioFromClientX(event.clientX))
  }

  function endDrag() {
    dragging.current = false
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") {
      setRatio((current) => clampRatio(current - 0.05, minRatio))
    } else if (event.key === "ArrowRight") {
      setRatio((current) => clampRatio(current + 0.05, minRatio))
    } else if (event.key === "Home") {
      setRatio(minRatio)
    } else if (event.key === "End") {
      setRatio(1 - minRatio)
    } else {
      return
    }
    event.preventDefault()
  }

  return (
    <div className="ui-split" ref={root}>
      <div className="ui-split-pane" style={{ flexBasis: `${ratio * 100}%` }}>
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={label}
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuemin={Math.round(minRatio * 100)}
        aria-valuemax={Math.round((1 - minRatio) * 100)}
        tabIndex={0}
        className="ui-split-handle"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={onKeyDown}
      />
      <div className="ui-split-pane ui-split-pane-right">
        {right}
      </div>
    </div>
  )
}

import { useState } from "react"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"

/** Persist user choices only, leaving the caller's defaults intact for new nodes. */
export function useExpansion(path: readonly (string | number)[], defaultExpanded = true) {
  const key = `audits.expansion:${JSON.stringify(path)}`
  function read() {
    const stored = localStorage.get<unknown>(key, defaultExpanded)
    return typeof stored === "boolean" ? stored : defaultExpanded
  }
  const [state, setState] = useState(() => ({ key, expanded: read() }))
  // A mounted view can switch audits without remounting its rows.
  const expanded = state.key === key ? state.expanded : read()

  function toggle() {
    const next = !expanded
    localStorage.set(key, next)
    setState({ key, expanded: next })
  }

  return [expanded, toggle] as const
}

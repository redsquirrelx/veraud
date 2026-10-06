import { useEffect, useState } from "react"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"

export interface TaskKindOption {
  kind: string
  label: string
  hint: string
}

export const TASK_KIND_OPTIONS: TaskKindOption[] = [
  { kind: "clone", label: "Clone", hint: "Initial repository download" },
  { kind: "pull", label: "Pull", hint: "Sync an attached checkout" },
  { kind: "fetch", label: "Fetch", hint: "Sync a detached checkout" },
  { kind: "checkout-branch", label: "Checkout branch", hint: "Switch branches" },
  { kind: "checkout-detach", label: "Checkout commit", hint: "Move to a specific commit" },
  { kind: "list-branches", label: "List branches", hint: "Read-only" },
  { kind: "rev-parse", label: "Resolve branch", hint: "Read-only" },
  { kind: "log-commits", label: "List commits", hint: "Read-only" },
]

const READ_KINDS = ["list-branches", "rev-parse", "log-commits"]
const STORAGE_KEY = "tasks.visibility"

export type TaskVisibility = Record<string, boolean>

export function defaultTaskVisibility(): TaskVisibility {
  const visibility: TaskVisibility = {}
  for (const option of TASK_KIND_OPTIONS) {
    visibility[option.kind] = READ_KINDS.includes(option.kind) === false
  }
  return visibility
}

export function loadTaskVisibility(): TaskVisibility {
  const defaults = defaultTaskVisibility()
  const stored = localStorage.get<TaskVisibility>(STORAGE_KEY, {})
  const merged = { ...defaults }
  for (const option of TASK_KIND_OPTIONS) {
    if (typeof stored[option.kind] === "boolean") {
      merged[option.kind] = stored[option.kind] as boolean
    }
  }
  return merged
}

export function saveTaskVisibility(visibility: TaskVisibility): void {
  localStorage.set(STORAGE_KEY, visibility)
}

export function isTaskVisible(task: Pick<ActiveTask, "kind" | "status">, visibility: TaskVisibility = loadTaskVisibility()): boolean {
  if (task.status === "Failed") {
    return true
  }
  return visibility[task.kind] ?? true
}

const VISIBILITY_CHANGED = "tasks-visibility-changed"

export function useTaskVisibility(): [TaskVisibility, (kind: string, visible: boolean) => void] {
  const [visibility, setVisibility] = useState(loadTaskVisibility)

  useEffect(() => {
    function reload() {
      setVisibility(loadTaskVisibility())
    }
    window.addEventListener(VISIBILITY_CHANGED, reload)
    return () => {
      window.removeEventListener(VISIBILITY_CHANGED, reload)
    }
  }, [])

  function update(kind: string, visible: boolean) {
    const next = { ...loadTaskVisibility(), [kind]: visible }
    saveTaskVisibility(next)
    setVisibility(next)
    window.dispatchEvent(new Event(VISIBILITY_CHANGED))
  }

  return [visibility, update]
}

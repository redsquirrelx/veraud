import { useEffect, useState } from "react"
import type { ParseKeys } from "i18next"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"

export interface TaskKindOption {
  kind: string
  labelKey: ParseKeys<"tasks">
  hintKey: ParseKeys<"tasks">
  /**
   * English fallback kept for consumers outside the i18n migration scope
   * (SettingsPage renders these directly). New code must translate
   * labelKey/hintKey at render time instead.
   * @deprecated Use labelKey with t() instead.
   */
  label: string
  /**
   * English fallback kept for consumers outside the i18n migration scope.
   * @deprecated Use hintKey with t() instead.
   */
  hint: string
}

export const TASK_KIND_OPTIONS: TaskKindOption[] = [
  { kind: "clone", labelKey: "kindOptions.clone.label", hintKey: "kindOptions.clone.hint", label: "Clone", hint: "Initial repository download" },
  { kind: "pull", labelKey: "kindOptions.pull.label", hintKey: "kindOptions.pull.hint", label: "Pull", hint: "Sync an attached checkout" },
  { kind: "fetch", labelKey: "kindOptions.fetch.label", hintKey: "kindOptions.fetch.hint", label: "Fetch", hint: "Sync a detached checkout" },
  { kind: "checkout-branch", labelKey: "kindOptions.checkoutBranch.label", hintKey: "kindOptions.checkoutBranch.hint", label: "Checkout branch", hint: "Switch branches" },
  { kind: "checkout-detach", labelKey: "kindOptions.checkoutDetach.label", hintKey: "kindOptions.checkoutDetach.hint", label: "Checkout commit", hint: "Move to a specific commit" },
  { kind: "list-branches", labelKey: "kindOptions.listBranches.label", hintKey: "kindOptions.listBranches.hint", label: "List branches", hint: "Read-only" },
  { kind: "rev-parse", labelKey: "kindOptions.revParse.label", hintKey: "kindOptions.revParse.hint", label: "Resolve branch", hint: "Read-only" },
  { kind: "log-commits", labelKey: "kindOptions.logCommits.label", hintKey: "kindOptions.logCommits.hint", label: "List commits", hint: "Read-only" },
]

const READ_KINDS = ["list-branches", "rev-parse", "log-commits"]
const STORAGE_KEY = "tasks.visibility"

/** Task kinds that rewrite the checkout under a running analysis. */
const SYNC_KINDS = ["clone", "pull", "fetch"]

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

/** Whether the project has a sync task (clone/pull/fetch) in flight. An
 *  analysis must not start while the checkout is being rewritten. */
export function isSyncActive(tasks: Pick<ActiveTask, "kind" | "projectId">[], projectId: number | null): boolean {
  if (projectId === null) {
    return false
  }
  return tasks.some((task) => task.projectId === projectId && SYNC_KINDS.includes(task.kind))
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

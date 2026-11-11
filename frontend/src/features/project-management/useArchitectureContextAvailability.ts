import { useEffect, useState } from "react"
import { getArchitectureContextAvailability, type ArchitectureContextAvailability } from "./architectureContextApi.ts"

/** A previous revision's response must never enable the newly selected revision. */
export function useArchitectureContextAvailability(projectId: number, commitHash: string | null,
  enabled: boolean, revision: string) {
  const key = `${projectId}:${commitHash}:${enabled}:${revision}`
  const [stored, setStored] = useState<{ key: string; status: "ready" | "failed"; value?: ArchitectureContextAvailability } | null>(null)
  useEffect(() => {
    if (!enabled || !commitHash) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      try {
        const value = await getArchitectureContextAvailability(projectId, commitHash!, controller.signal)
        if (controller.signal.aborted) return
        if (value.projectId !== projectId || value.commitHash !== commitHash || typeof value.available !== "boolean"
          || (value.available && (!value.executionId || !["complete", "partial"].includes(value.executionStatus ?? "")))) {
          throw new Error("Invalid context availability")
        }
        setStored({ key, status: "ready", value })
        if (!value.available) timer = setTimeout(() => void load(), 5000)
      } catch {
        if (controller.signal.aborted) return
        setStored({ key, status: "failed" })
        timer = setTimeout(() => void load(), 5000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [projectId, commitHash, enabled, revision, key])
  const current = stored?.key === key ? stored : null
  return { available: current?.status === "ready" && current.value?.available === true,
    status: current?.status ?? "loading", executionStatus: current?.value?.executionStatus ?? null }
}

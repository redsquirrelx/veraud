import { useEffect, useRef, useState } from "react"
import { PROJECT_PIPELINE, runProjectPipeline, type ProjectPipelineProgress, type ProjectPipelineStep } from "./projectPipeline.ts"
import type { ArchitectureContextOutput } from "./architectureContextApi.ts"
import type { ParseKeys } from "i18next"
import { ProjectPipelineError } from "./projectPipelineErrors.ts"

interface PipelineState {
  status: "idle" | "running" | "completed" | "failed"
  progress: ProjectPipelineProgress | null
  contextStatus?: "complete" | "partial"
  errorKey?: ParseKeys<"projects">
  runId?: number
}

const idle: PipelineState = { status: "idle", progress: null }

export function useProjectPipeline(projectId: number | null, steps: readonly ProjectPipelineStep[] = PROJECT_PIPELINE) {
  const [state, setState] = useState<PipelineState>(idle)
  const [trackedProject, setTrackedProject] = useState(projectId)
  const active = useRef<AbortController | null>(null)

  if (trackedProject !== projectId) {
    setTrackedProject(projectId)
    setState(idle)
  }

  useEffect(() => {
    return () => {
      active.current?.abort()
      active.current = null
    }
  }, [projectId])

  async function start(branch: string, commitHash: string) {
    if (projectId === null || active.current) return
    const controller = new AbortController()
    active.current = controller
    setState((current) => ({ status: "running", progress: null, runId: (current.runId ?? 0) + 1 }))
    try {
      const results = await runProjectPipeline(steps, { projectId, branch, commitHash }, controller.signal, (progress) => {
        if (!controller.signal.aborted) setState((current) => ({ ...current, status: "running", progress }))
      })
      const context = results.get("architecture-context") as ArchitectureContextOutput | undefined
      if (!controller.signal.aborted) setState((current) => ({ ...current, status: "completed",
        ...(context?.execution_status === "complete" || context?.execution_status === "partial"
          ? { contextStatus: context.execution_status } : {}),
      }))
    } catch (error) {
      // Do not display arbitrary transport/provider errors in the UI.
      if (!controller.signal.aborted) setState((current) => ({ ...current, status: "failed",
        ...(error instanceof ProjectPipelineError ? { errorKey: error.labelKey } : {}),
      }))
    } finally {
      if (active.current === controller) active.current = null
    }
  }

  return { ...state, running: state.status === "running", start }
}

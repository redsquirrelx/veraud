import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiError, getAgentExecution, requestProjectArchitecture, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { mergeExecution } from "../../shared/agent-monitor/mergeExecution.ts"
import { DEFAULT_PIPELINE_ID, pipelineById } from "./pipelines.ts"

export type AnalysisPhase = "idle" | "starting" | "tracking" | "done" | "error"

const POLL_INTERVAL_MS = 5000

function lastExecutionKey(projectId: number): string {
  return `analysis.lastExecution.${projectId}`
}

function describeFailure(failure: unknown, fallback: string): string {
  if (failure instanceof ApiError) {
    return failure.message
  }
  return fallback
}

function isFinished(execution: AgentExecution | null): boolean {
  return execution?.status === "Completed" || execution?.status === "Failed"
}

export function useAnalysis(projectId: number | null, options?: { pollIntervalMs?: number }) {
  const { t } = useTranslation("projects")
  const live = useAgentExecutions()
  const pollIntervalMs = options?.pollIntervalMs ?? POLL_INTERVAL_MS
  const [trackedProject, setTrackedProject] = useState<number | null>(projectId)
  const [seed, setSeed] = useState<AgentExecution | null>(null)
  const [polled, setPolled] = useState<AgentExecution | null>(null)
  const [initialExecutions, setInitialExecutions] = useState<AgentExecution[]>([])
  const [starting, setStarting] = useState(false)
  const [failure, setFailure] = useState("")
  const [tracked, setTracked] = useState(false)

  // Switching projects drops the previous run (render-phase reset).
  if (trackedProject !== projectId) {
    setTrackedProject(projectId)
    setSeed(null)
    setPolled(null)
    setInitialExecutions([])
    setStarting(false)
    setFailure("")
    setTracked(false)
  }

  const wantedId = seed?.id ?? polled?.id ?? null
  const liveExecution = wantedId === null ? null : live.find((item) => item.id === wantedId)
  const execution = useMemo(() => {
    let latest = seed
    if (polled) latest = mergeExecution(latest, polled)
    if (liveExecution) latest = mergeExecution(latest, liveExecution)
    return latest
  }, [liveExecution, polled, seed])

  let phase: AnalysisPhase = "idle"
  if (failure !== "") {
    phase = "error"
  } else if (isFinished(execution)) {
    phase = "done"
  } else if (execution !== null) {
    phase = "tracking"
  } else if (starting) {
    phase = "starting"
  }

  // Reopen the last run after a reload or navigation.
  useEffect(() => {
    if (projectId === null) {
      return
    }
    const stored = localStorage.get<number | null>(lastExecutionKey(projectId), null)
    if (stored === null || Number.isInteger(stored) === false) {
      return
    }
    let alive = true
    void getAgentExecution(stored).then(
      (restored) => {
        if (alive) {
          setPolled(restored)
        }
      },
      () => {
        // The row is gone: forget it instead of retrying forever.
        localStorage.remove(lastExecutionKey(projectId))
      }
    )
    return () => {
      alive = false
    }
  }, [projectId])

  // Backstop for a silent websocket: while the run is open, refresh it so the
  // result always lands even when no event arrives.
  useEffect(() => {
    if (wantedId === null || isFinished(execution)) {
      return
    }
    const timer = setInterval(() => {
      void getAgentExecution(wantedId).then(
        (next) => setPolled(next),
        () => {
          // Keep tracking: a transient failure must not kill the run view.
        }
      )
    }, pollIntervalMs)
    return () => clearInterval(timer)
  })

  async function start(branch: string, commitHash: string, pipelineId: string = DEFAULT_PIPELINE_ID) {
    if (projectId === null || starting) {
      return
    }
    setStarting(true)
    setFailure("")
    setSeed(null)
    setPolled(null)
    setInitialExecutions([])
    setTracked(true)
    try {
      // The tracked row is the one that finishes last for the chosen
      // pipeline, so progress follows the run to completion.
      const option = pipelineById(pipelineId)
      const response = await requestProjectArchitecture(projectId, branch, commitHash)
      const rows = Object.values(response.executions)
      setInitialExecutions(rows)
      const trackedRow = (response.executions as Record<string, AgentExecution>)[option.trackedStage] ?? rows[0]!
      localStorage.set(lastExecutionKey(projectId), trackedRow.id)
      setSeed(trackedRow)
    } catch (error) {
      setFailure(describeFailure(error, t("analysis.errors.startFailed")))
    } finally {
      setStarting(false)
    }
  }

  function reset() {
    if (projectId !== null) {
      localStorage.remove(lastExecutionKey(projectId))
    }
    setSeed(null)
    setPolled(null)
    setInitialExecutions([])
    setStarting(false)
    setFailure("")
    setTracked(false)
  }

  /** Displays a stored run, e.g. picked from the analyzed versions. */
  function show(execution: AgentExecution | null) {
    setStarting(false)
    setFailure("")
    setSeed(null)
    setPolled(execution)
    setInitialExecutions([])
    setTracked(false)
    if (projectId !== null && execution !== null) {
      localStorage.set(lastExecutionKey(projectId), execution.id)
    }
  }

  return {
    phase,
    execution,
    initialExecutions,
    message: failure,
    analyzing: phase === "starting" || phase === "tracking",
    tracked,
    start,
    reset,
    show,
  }
}

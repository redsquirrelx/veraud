import { useEffect, useState } from "react"
import { ApiError, getAgentExecution, requestAnalysis, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"

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
  const live = useAgentExecutions()
  const pollIntervalMs = options?.pollIntervalMs ?? POLL_INTERVAL_MS
  const [trackedProject, setTrackedProject] = useState<number | null>(projectId)
  const [seed, setSeed] = useState<AgentExecution | null>(null)
  const [polled, setPolled] = useState<AgentExecution | null>(null)
  const [starting, setStarting] = useState(false)
  const [failure, setFailure] = useState("")
  const [tracked, setTracked] = useState(false)

  // Switching projects drops the previous run (render-phase reset).
  if (trackedProject !== projectId) {
    setTrackedProject(projectId)
    setSeed(null)
    setPolled(null)
    setStarting(false)
    setFailure("")
    setTracked(false)
  }

  const wantedId = seed?.id ?? polled?.id ?? null
  // Live events win; otherwise the poll beats the stale start snapshot.
  const execution = wantedId === null ? null : (live.find((item) => item.id === wantedId) ?? polled ?? seed)

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

  async function start(branch: string, commitHash: string) {
    if (projectId === null || starting) {
      return
    }
    setStarting(true)
    setFailure("")
    setSeed(null)
    setPolled(null)
    setTracked(true)
    try {
      const response = await requestAnalysis(projectId, branch, commitHash)
      localStorage.set(lastExecutionKey(projectId), response.execution.id)
      setSeed(response.execution)
    } catch (error) {
      setFailure(describeFailure(error, "Could not analyze the project"))
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
    setTracked(false)
    if (projectId !== null && execution !== null) {
      localStorage.set(lastExecutionKey(projectId), execution.id)
    }
  }

  return {
    phase,
    execution,
    message: failure,
    analyzing: phase === "starting" || phase === "tracking",
    tracked,
    start,
    reset,
    show,
  }
}

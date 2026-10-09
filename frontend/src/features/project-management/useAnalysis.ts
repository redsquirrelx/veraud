import { useState } from "react"
import { ApiError, requestAnalysis, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"

export type AnalysisPhase = "idle" | "starting" | "tracking" | "done" | "error"

function describeFailure(failure: unknown, fallback: string): string {
  if (failure instanceof ApiError) {
    return failure.message
  }
  return fallback
}

export function useAnalysis(projectId: number | null) {
  const live = useAgentExecutions()
  const [seed, setSeed] = useState<AgentExecution | null>(null)
  const [starting, setStarting] = useState(false)
  const [failure, setFailure] = useState("")

  const execution = seed === null ? null : (live.find((item) => item.id === seed.id) ?? seed)
  const finished = execution?.status === "Completed" || execution?.status === "Failed"

  let phase: AnalysisPhase = "idle"
  if (failure !== "") {
    phase = "error"
  } else if (finished) {
    phase = "done"
  } else if (execution !== null) {
    phase = "tracking"
  } else if (starting) {
    phase = "starting"
  }

  async function start(branch: string, commitHash: string) {
    if (projectId === null || starting) {
      return
    }
    setStarting(true)
    setFailure("")
    setSeed(null)
    try {
      const response = await requestAnalysis(projectId, branch, commitHash)
      setSeed(response.execution)
    } catch (error) {
      setFailure(describeFailure(error, "Could not analyze the project"))
    } finally {
      setStarting(false)
    }
  }

  function reset() {
    setSeed(null)
    setStarting(false)
    setFailure("")
  }

  return {
    phase,
    execution,
    message: failure,
    analyzing: phase === "starting" || phase === "tracking",
    start,
    reset,
  }
}

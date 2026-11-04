import { useCallback, useEffect, useRef, useState } from "react"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"
import { getProjectGraph, startProjectGraph, type ProjectGraph } from "./projectGraphApi.ts"

interface GraphState {
  key: string
  graph: ProjectGraph | null
  starting: boolean
  error: "startError" | "loadError" | null
  completedTaskId: number | null
}

function emptyState(key: string): GraphState { return { key, graph: null, starting: false, error: null, completedTaskId: null } }

export function useProjectGraph(projectId: number | null, branch: string | null, commitHash: string | null, tasks: ActiveTask[]) {
  const key = `${projectId}:${commitHash}`
  const [stored, setState] = useState<GraphState>(() => emptyState(key))
  // Never display the previous revision while the next request is loading.
  const state = stored.key === key ? stored : emptyState(key)
  const generation = useRef(0)
  const startLock = useRef(false)
  const [revision, setRevision] = useState(0)
  const relevantTasks = tasks.filter((task) => task.projectId === projectId && task.kind === "graph.extract")
  // Object identity changes on every callback, including same-status progress events.
  const taskEvent = relevantTasks.find((task) => task.id === state.graph?.taskId) ?? relevantTasks.at(-1)
  const graphAvailable = state.graph?.graphAvailable === true || state.graph?.previousGraphTaskId != null

  useEffect(() => {
    const current = generation.current + 1
    generation.current = current
    startLock.current = false
    return () => { generation.current = current + 1 }
  }, [key])

  useEffect(() => {
    if (projectId === null || commitHash === null) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function refresh() {
      try {
        const next = await getProjectGraph(projectId!, commitHash!, controller.signal)
        if (controller.signal.aborted) return
        setState((current) => {
          const previous = current.key === key ? current : emptyState(key)
          const completed = next?.graphAvailable && previous.graph?.taskId === next.taskId
            && ["Queued", "Running"].includes(previous.graph.status)
          return { ...previous, graph: next,
            completedTaskId: completed ? next.taskId : previous.completedTaskId,
            error: previous.error === "startError" ? "startError" : null }
        })
        if (next === null || next.status === "Queued" || next.status === "Running") timer = setTimeout(() => void refresh(), 3000)
      } catch {
        if (!controller.signal.aborted) {
          setState((current) => ({ ...(current.key === key ? current : emptyState(key)), error: "loadError" }))
          timer = setTimeout(() => void refresh(), 5000)
        }
      }
    }
    void refresh()
    return () => { controller.abort(); if (timer) clearTimeout(timer) }
  }, [projectId, commitHash, key, taskEvent, revision])

  const start = useCallback(async (regenerate = false) => {
    if (projectId === null || branch === null || commitHash === null || startLock.current) return
    if (graphAvailable && !regenerate) return
    startLock.current = true
    setState((current) => ({ ...(current.key === key ? current : emptyState(key)), starting: true, error: null }))
    const currentGeneration = generation.current
    try {
      const next = await startProjectGraph(projectId, branch, commitHash, regenerate)
      if (currentGeneration === generation.current) {
        setState((current) => ({ key, graph: next, starting: false, error: null,
          completedTaskId: next.graphAvailable && !next.reused ? next.taskId : current.completedTaskId }))
        setRevision((value) => value + 1)
      }
    } catch {
      if (currentGeneration === generation.current) setState((current) => ({ ...current, error: "startError" }))
    } finally {
      if (currentGeneration === generation.current) {
        setState((current) => ({ ...current, starting: false }))
        startLock.current = false
      }
    }
  }, [projectId, branch, commitHash, key, graphAvailable])

  return { ...state, start, running: state.starting || state.graph?.status === "Queued" || state.graph?.status === "Running" }
}

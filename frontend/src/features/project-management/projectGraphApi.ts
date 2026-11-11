import { backendHttpUrl, requestJson } from "../../infrastructure/http-client/httpClient.ts"
import type { GraphifyGraph } from "./structuralGraphModel.ts"

export interface ProjectGraph {
  taskId: number
  projectId: number
  branch: string
  commitHash: string
  status: "Queued" | "Running" | "Succeded" | "Failed"
  phase: "queued" | "preparing" | "extracting" | "saving" | "completed" | "failed"
  error: string | null
  createdAt?: string | null
  graphAvailable: boolean
  reused?: boolean
  previousGraphTaskId?: number | null
}

export async function getProjectGraph(projectId: number, commitHash: string, signal?: AbortSignal) {
  const graph = await requestJson<ProjectGraph | null>(`/api/projects/${projectId}/graph?commitHash=${commitHash}`, "Could not load graph status", { signal })
  if (graph !== null && (typeof graph.taskId !== "number" || typeof graph.phase !== "string")) throw new Error("Invalid graph status")
  return graph
}

export function startProjectGraph(projectId: number, branch: string, commitHash: string, regenerate = false, signal?: AbortSignal) {
  return requestJson<ProjectGraph>(`/api/projects/${projectId}/graph`, "Could not start graph extraction", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ branch, commitHash, ...(regenerate ? { regenerate: true } : {}) }), signal,
  })
}

export function projectGraphArtifactUrl(projectId: number, taskId: number) {
  return `${backendHttpUrl()}/api/projects/${projectId}/graph/${taskId}/artifact`
}

export function getProjectGraphArtifact(projectId: number, taskId: number, signal?: AbortSignal) {
  return requestJson<GraphifyGraph>(`/api/projects/${projectId}/graph/${taskId}/artifact`, "Could not load graph data", { signal })
}

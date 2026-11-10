import { ApiError, backendHttpUrl, requestJson, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { ProjectPipelineError } from "./projectPipelineErrors.ts"

export interface ArchitectureContextOutput {
  schema_version: string
  execution_status: string
  document_index?: { commit?: string; [key: string]: unknown }
  knowledge?: unknown[]
  knowledge_issues?: unknown[]
  validation_errors?: unknown[]
  [key: string]: unknown
}

export interface ArchitectureContextAvailability {
  projectId: number
  commitHash: string
  available: boolean
  executionId: number | null
  executionStatus: "complete" | "partial" | null
}

export interface ArchitectureContextContent {
  projectId: number
  commitHash: string
  executionId: number
  executionStatus: "complete" | "partial"
  schemaVersion: string
  createdAt: string
  data: Record<string, unknown>
}

export async function startArchitectureContext(context: { projectId: number; branch: string; commitHash: string }, signal?: AbortSignal): Promise<AgentExecution> {
  const response = await fetch(`${backendHttpUrl()}/api/agent-executions/direct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agentType: "architecture_context", project: { projectId: context.projectId, branch: context.branch, commitHash: context.commitHash } }),
    signal,
  })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const agents = (body as { agents?: unknown } | null)?.agents
    if (response.status === 422 && Array.isArray(agents)) {
      throw new ProjectPipelineError("analyze.pipeline.contextConfigurationError")
    }
    const message = typeof (body as { error?: unknown } | null)?.error === "string" ? ((body as { error: string }).error) : "Could not start architecture context"
    throw new ApiError(response.status, message, "client")
  }
  return body as AgentExecution
}

export async function getArchitectureContextExecution(executionId: number, signal?: AbortSignal): Promise<AgentExecution> {
  return requestJson<AgentExecution>(`/api/agent-executions/${executionId}`, "Could not load the agent execution", { signal }, false)
}

export async function getArchitectureContextAvailability(projectId: number, commitHash: string, signal?: AbortSignal) {
  return requestJson<ArchitectureContextAvailability>(`/api/projects/${projectId}/architecture-context?commitHash=${commitHash}`, "Could not load architecture context availability", { signal })
}

export async function getArchitectureContextContent(projectId: number, commitHash: string, signal?: AbortSignal) {
  try {
    const context = await requestJson<ArchitectureContextContent>(`/api/projects/${projectId}/architecture-context/content?commitHash=${commitHash}`, "Could not load architecture context", { signal })
    if (!context || typeof context.createdAt !== "string" || Number.isNaN(Date.parse(context.createdAt)) || typeof context.data !== "object" || context.data === null) {
      throw new Error("Invalid architecture context")
    }
    return context
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export class ApiError extends Error {
  status: number
  messageSource?: "server" | "client"

  constructor(status: number, message: string, messageSource?: "server" | "client") {
    super(message)
    this.status = status
    this.messageSource = messageSource
  }
}

export interface RegisteredProject {
  id: number
  repositoryOwner: string
  repositoryName: string
  status: string
}

const baseUrl = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501"

export function backendHttpUrl(): string {
  return baseUrl
}

export function backendWsUrl(): string {
  return `${baseUrl.replace(/^http/, "ws")}/ws`
}

/** Reads one JSON response while preserving each endpoint's existing error-message policy. */
export async function requestJson<T>(path: string, fallback: string, init?: RequestInit, useBackendMessage = true): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, init)
  if (!response.ok && !useBackendMessage) {
    throw new ApiError(response.status, fallback, "client")
  }
  const body: unknown = await response.json()
  if (!response.ok) {
    const serverMessage = typeof body === "object" && body !== null && "message" in body
      && typeof body.message === "string" ? body.message : undefined
    throw new ApiError(response.status, serverMessage ?? fallback, serverMessage === undefined ? "client" : "server")
  }
  return body as T
}

export interface ActiveTask {
  command?: string | null
  id: number
  projectId: number
  repositoryOwner: string
  repositoryName: string
  description: string | null
  status: string
  kind: string
  exitCode: number | null
}

export interface ProjectSummary {
  id: number
  repositoryOwner: string
  repositoryName: string
  cloneProtocol: "ssh" | "https"
  status: string
  registeredAt: string
  lastSyncedAt: string | null
  branch: string | null
  commitHash: string | null
}

export async function listProjects(): Promise<ProjectSummary[]> {
  return requestJson("/api/projects", "Could not load projects", undefined, false)
}

export async function listActiveTasks(): Promise<ActiveTask[]> {
  return requestJson("/api/tasks/active", "Could not load tasks", undefined, false)
}

export async function syncProject(id: number): Promise<ProjectSummary> {
  return requestJson(`/api/projects/${id}/sync`, "Could not sync the project", {
    method: "POST",
    signal: AbortSignal.timeout(600000),
  })
}

export async function registerProject(repositoryUrl: string, shallowClone = false): Promise<RegisteredProject> {
  return requestJson("/api/projects", "Unexpected error", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repositoryUrl, shallowClone }),
    signal: AbortSignal.timeout(600000),
  })
}

export interface GitBranchList {
  branches: string[]
  currentBranch: string | null
  detachedHash: string | null
  taskId: number
}

export interface GitCommitEntry {
  commitHash: string
  subject: string
}

export interface GitCommitList {
  branch: string
  commits: GitCommitEntry[]
  limit: number
  offset: number
  taskId: number
}

export interface GitCheckout {
  commitHash: string
  taskId: number
}

async function postGit<T>(id: number, action: string, body: unknown): Promise<T> {
  return requestJson<T>(`/api/projects/${id}/git/${action}`, "Git operation failed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(600000),
  })
}

export async function listBranches(id: number): Promise<GitBranchList> {
  return postGit<GitBranchList>(id, "branches", {})
}

export async function listCommits(id: number, branch: string, limit?: number, offset?: number): Promise<GitCommitList> {
  return postGit<GitCommitList>(id, "log", { branch, limit, offset })
}

export async function checkoutCommit(id: number, commitHash: string): Promise<GitCheckout> {
  return postGit<GitCheckout>(id, "checkout", { commitHash })
}

export interface GitBranchCheckout {
  branch: string
  taskId: number
}

export async function checkoutBranch(id: number, branch: string): Promise<GitBranchCheckout> {
  return postGit<GitBranchCheckout>(id, "checkout-branch", { branch })
}

export interface ProjectFile {
  path: string
  content: string
  size: number
}

export async function readProjectFile(id: number, path: string): Promise<ProjectFile> {
  return requestJson(`/api/projects/${id}/file`, "Could not read the file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
    signal: AbortSignal.timeout(600000),
  })
}

export interface GitTree {
  files: string[]
  taskId: number
}

export async function listProjectFiles(id: number): Promise<GitTree> {
  return postGit<GitTree>(id, "tree", {})
}

export interface AgentInvocation {
  phase?: string | null
  phase_sequence?: number
  invocation_id: string
  parent_invocation_id: string | null
  agent_id: string
  run_id: string
  status: "running" | "completed" | "partial" | "failed" | "cancelled" | "timeout"
  started_at: string
  finished_at: string | null
  input_tokens: number | null
  output_tokens: number | null
  error: string | null
}

export interface AgentExecution {
  cancellationRequestedAt?: string | null
  invocations?: AgentInvocation[]
  monitorContext?: {
    project: { id: number, repositoryOwner: string, repositoryName: string } | null
    branch: string | null
    commitHash: string | null
    evaluationType: string | null
    qualityAttributes: string[]
    workflowIds: string[]
  }
  configuration?: AgentConfiguration | null
  id: number
  evaluationId: number | null
  agentType: string
  status: string
  result: string | null
  error: string | null
  inputTokens: number | null
  outputTokens: number | null
  estimatedTokens?: number | null
  interruptionReason?: string | null
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
}

export interface AuditCancellationResult {
  id: number
  executionStatus: string
  auditStatus: string | null
  cancellationRequestedAt?: string | null
  runId?: string | null
  finishedAt: string | null
  error: string | null
}

const cancellationRequests = new Map<string, Promise<AuditCancellationResult>>()

export function cancelQualityAudit(projectId: number, auditId: number): Promise<AuditCancellationResult> {
  if (!Number.isInteger(projectId) || !Number.isInteger(auditId) || projectId <= 0 || auditId <= 0) {
    return Promise.reject(new Error("Only persisted project audits can be cancelled"))
  }
  const path = `/api/projects/${projectId}/audits/${auditId}/cancel`
  const pending = cancellationRequests.get(path)
  if (pending) return pending
  const request = requestJson<AuditCancellationResult>(path, "Could not request audit cancellation", {
    method: "POST", signal: AbortSignal.timeout(15000),
  }).then((result) => {
    if (result.id !== auditId) throw new Error("Cancellation response belongs to another audit")
    if (!["Waiting", "Running", "Completed", "Failed"].includes(result.executionStatus)
      || (result.auditStatus !== null && typeof result.auditStatus !== "string")) {
      throw new Error("Invalid cancellation response")
    }
    return result
  }).finally(() => { cancellationRequests.delete(path) })
  cancellationRequests.set(path, request)
  return request
}

export interface ProjectArchitectureRequest {
  versionId: number
  evaluationId: number
  executions: { orientation: AgentExecution; architecture: AgentExecution; semantic_validation: AgentExecution }
}

export async function requestProjectArchitecture(id: number, branch: string, commitHash: string): Promise<ProjectArchitectureRequest> {
  return requestJson(`/api/projects/${id}/architecture`, "Could not analyze the project", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ branch, commitHash }),
    signal: AbortSignal.timeout(600000),
  })
}

export async function getAgentExecution(executionId: number, monitor = false): Promise<AgentExecution> {
  return requestJson(`/api/agent-executions/${executionId}${monitor ? "?monitor=true" : ""}`,
    "Could not load the agent execution", undefined, false)
}

export interface VersionAnalysisSummary {
  id: number
  branch: string | null
  commitHash: string | null
  analysisStatus: string
  analyzedAt: string | null
  evaluationId: number | null
  executions: AgentExecution[]
  /** Analyzer (or first historical run), null when the evaluation has no runs. */
  execution?: AgentExecution | null
  derivedStatus: string
}

export async function listVersions(id: number): Promise<VersionAnalysisSummary[]> {
  return requestJson(`/api/projects/${id}/versions`, "Could not load analyzed versions", undefined, false)
}

export interface AiModelSummary {
  id: number
  name: string
  inUse: boolean
}

export interface AiCredentialSummary {
  id: number
  name: string
  apiKeyPreview: string
  inUse: boolean
}

export interface AiProviderDetail {
  id: number
  name: string
  models: AiModelSummary[]
  credentials: AiCredentialSummary[]
}

export async function listAiProviders(): Promise<AiProviderDetail[]> {
  return requestJson("/api/ai-providers", "Could not load AI providers", undefined, false)
}

async function postAi<T>(aiProviderId: number, resource: string, body: unknown): Promise<T> {
  return requestJson<T>(`/api/ai-providers/${aiProviderId}/${resource}`, "AI provider request failed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export interface AgentConfiguration {
  model: { id: number, name: string, providerId: number, providerName: string }
  credential: { id: number, name: string, providerId: number, providerName: string }
  temperature: number | null
  maxTokens: number | null
  tokenBudget?: number | null
  absoluteTokenLimit?: number | null
}

export interface AgentSettings {
  parentAgentTypes?: string[]
  childAgentTypes?: string[]
  requiresModel?: boolean
  modelConfigurationAgentType?: string | null
  availability?: string
  role?: string
  executionModes?: string[]
  agentType: string
  name?: string
  qualityAttributes: string[]
  workflowIds: string[]
  configured: boolean
  configuration: AgentConfiguration | null
  verification?: { status: "not_verified" | "verified" | "failed", checkedAt: string | null, message: string | null, reason?: string }
}

export async function listAgentSettings(signal?: AbortSignal): Promise<AgentSettings[]> {
  return requestJson("/api/agent-settings", "Could not load agent settings", { signal })
}

export async function saveAgentSettings(agentType: string, modelId: number, credentialId: number, options: { temperature?: number | null, maxTokens?: number | null, tokenBudget?: number | null, absoluteTokenLimit?: number | null } = {}): Promise<AgentSettings> {
  return requestJson(`/api/agent-settings/${encodeURIComponent(agentType)}`, "Could not save agent settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ modelId, credentialId, ...options }),
  })
}

export async function verifyAgentSettings(agentType: string): Promise<AgentSettings> {
  return requestJson(`/api/agent-settings/${encodeURIComponent(agentType)}/verify`, "Could not verify model access", { method: "POST" })
}

export async function syncAgentSettings(): Promise<AgentSettings[]> {
  return requestJson("/api/agent-settings/sync", "Could not synchronize agent catalog", { method: "POST" })
}

export async function saveQualityCategory(attribute: string, modelId: number, credentialId: number): Promise<AgentSettings[]> {
  return requestJson(`/api/agent-settings/categories/${encodeURIComponent(attribute)}`, "Could not save category model access", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ modelId, credentialId }),
  })
}

async function patchAi<T>(aiProviderId: number, resource: string, id: number, body: unknown): Promise<T> {
  return requestJson<T>(`/api/ai-providers/${aiProviderId}/${resource}/${id}`, "AI provider request failed", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

async function deleteAi(aiProviderId: number, resource: string, id: number): Promise<void> {
  const response = await fetch(`${baseUrl}/api/ai-providers/${aiProviderId}/${resource}/${id}`, {
    method: "DELETE",
  })

  if (response.status === 204) {
    return
  }

  const payload = (await response.json()) as { message?: string }

  throw new ApiError(response.status, payload.message ?? "AI provider request failed", payload.message == null ? "client" : "server")
}

export async function createAiModel(aiProviderId: number, name: string): Promise<AiModelSummary> {
  return postAi<AiModelSummary>(aiProviderId, "models", { name })
}

export async function updateAiModel(aiProviderId: number, modelId: number, name: string): Promise<AiModelSummary> {
  return patchAi<AiModelSummary>(aiProviderId, "models", modelId, { name })
}

export async function deleteAiModel(aiProviderId: number, modelId: number): Promise<void> {
  return deleteAi(aiProviderId, "models", modelId)
}

export async function createAiCredential(aiProviderId: number, name: string, apiKey: string): Promise<AiCredentialSummary> {
  return postAi<AiCredentialSummary>(aiProviderId, "credentials", { name, apiKey })
}

export async function updateAiCredential(aiProviderId: number, credentialId: number, name: string, apiKey?: string): Promise<AiCredentialSummary> {
  return patchAi<AiCredentialSummary>(aiProviderId, "credentials", credentialId, { name, ...(apiKey === undefined ? {} : { apiKey }) })
}

export async function deleteAiCredential(aiProviderId: number, credentialId: number): Promise<void> {
  return deleteAi(aiProviderId, "credentials", credentialId)
}

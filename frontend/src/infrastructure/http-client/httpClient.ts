export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export interface RegisteredProject {
  id: number
  repositoryOwner: string
  repositoryName: string
  status: string
}

const baseUrl = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501"

export function backendWsUrl(): string {
  return `${baseUrl.replace(/^http/, "ws")}/ws`
}

export interface ActiveTask {
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
  status: string
  registeredAt: string
  lastSyncedAt: string | null
  branch: string | null
  commitHash: string | null
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const response = await fetch(`${baseUrl}/api/projects`)

  if (!response.ok) {
    throw new ApiError(response.status, "Could not load projects")
  }

  return (await response.json()) as ProjectSummary[]
}

export async function listActiveTasks(): Promise<ActiveTask[]> {
  const response = await fetch(`${baseUrl}/api/tasks/active`)

  if (!response.ok) {
    throw new ApiError(response.status, "Could not load tasks")
  }

  return (await response.json()) as ActiveTask[]
}

export async function syncProject(id: number): Promise<ProjectSummary> {
  const response = await fetch(`${baseUrl}/api/projects/${id}/sync`, {
    method: "POST",
    signal: AbortSignal.timeout(600000),
  })

  const body = (await response.json()) as { message?: string }

  if (!response.ok) {
    throw new ApiError(response.status, body.message ?? "Could not sync the project")
  }

  return body as ProjectSummary
}

export async function registerProject(repositoryUrl: string): Promise<RegisteredProject> {
  const response = await fetch(`${baseUrl}/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repositoryUrl }),
    signal: AbortSignal.timeout(600000),
  })

  const body = (await response.json()) as { message?: string }

  if (!response.ok) {
    throw new ApiError(response.status, body.message ?? "Unexpected error")
  }

  return body as RegisteredProject
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
  const response = await fetch(`${baseUrl}/api/projects/${id}/git/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(600000),
  })

  const payload = (await response.json()) as { message?: string }

  if (!response.ok) {
    throw new ApiError(response.status, payload.message ?? "Git operation failed")
  }

  return payload as T
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
  const response = await fetch(`${baseUrl}/api/projects/${id}/file`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
    signal: AbortSignal.timeout(600000),
  })

  const body = (await response.json()) as { message?: string }

  if (!response.ok) {
    throw new ApiError(response.status, body.message ?? "Could not read the file")
  }

  return body as ProjectFile
}

export interface GitTree {
  files: string[]
  taskId: number
}

export async function listProjectFiles(id: number): Promise<GitTree> {
  return postGit<GitTree>(id, "tree", {})
}

export interface AgentExecution {
  id: number
  evaluationId: number | null
  agentType: string
  status: string
  result: string | null
  error: string | null
  inputTokens: number | null
  outputTokens: number | null
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
}

export interface AnalysisRequest {
  versionId: number
  evaluationId: number
  execution: AgentExecution
}

export async function requestAnalysis(id: number, branch: string, commitHash: string): Promise<AnalysisRequest> {
  const response = await fetch(`${baseUrl}/api/projects/${id}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ branch, commitHash }),
    signal: AbortSignal.timeout(600000),
  })

  const body = (await response.json()) as { message?: string }

  if (!response.ok) {
    throw new ApiError(response.status, body.message ?? "Could not analyze the project")
  }

  return body as AnalysisRequest
}

export async function getAgentExecution(executionId: number): Promise<AgentExecution> {
  const response = await fetch(`${baseUrl}/api/agent-executions/${executionId}`)

  if (!response.ok) {
    throw new ApiError(response.status, "Could not load the agent execution")
  }

  return (await response.json()) as AgentExecution
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
  const response = await fetch(`${baseUrl}/api/ai-providers`)

  if (!response.ok) {
    throw new ApiError(response.status, "Could not load AI providers")
  }

  return (await response.json()) as AiProviderDetail[]
}

async function postAi<T>(aiProviderId: number, resource: string, body: unknown): Promise<T> {
  const response = await fetch(`${baseUrl}/api/ai-providers/${aiProviderId}/${resource}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })

  const payload = (await response.json()) as { message?: string }

  if (!response.ok) {
    throw new ApiError(response.status, payload.message ?? "AI provider request failed")
  }

  return payload as T
}

async function deleteAi(aiProviderId: number, resource: string, id: number): Promise<void> {
  const response = await fetch(`${baseUrl}/api/ai-providers/${aiProviderId}/${resource}/${id}`, {
    method: "DELETE",
  })

  if (response.status === 204) {
    return
  }

  const payload = (await response.json()) as { message?: string }

  throw new ApiError(response.status, payload.message ?? "AI provider request failed")
}

export async function createAiModel(aiProviderId: number, name: string): Promise<AiModelSummary> {
  return postAi<AiModelSummary>(aiProviderId, "models", { name })
}

export async function deleteAiModel(aiProviderId: number, modelId: number): Promise<void> {
  return deleteAi(aiProviderId, "models", modelId)
}

export async function createAiCredential(aiProviderId: number, name: string, apiKey: string): Promise<AiCredentialSummary> {
  return postAi<AiCredentialSummary>(aiProviderId, "credentials", { name, apiKey })
}

export async function deleteAiCredential(aiProviderId: number, credentialId: number): Promise<void> {
  return deleteAi(aiProviderId, "credentials", credentialId)
}

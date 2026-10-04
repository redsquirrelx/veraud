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

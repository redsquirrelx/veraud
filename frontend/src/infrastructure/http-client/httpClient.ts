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

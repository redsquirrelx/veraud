import { existsSync, readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { GithubClient, RepoNotAccessibleError, parseGithubUrl } from "../../infrastructure/github-client/github.client.js"
import { TaskService } from "../task/task.service.js"
import type { TaskCommand } from "../../infrastructure/task-runner/task.runner.js"
import type { ProjectStore, StoredProjectDetails } from "./project.repository.js"

export class InvalidUrlError extends Error {}
export class DuplicateProjectError extends Error {}
export class ProjectNotFoundError extends Error {}
export class SyncFailedError extends Error {}
export class InvalidGitRequestError extends Error {}
export class WorkspaceMissingError extends Error {}
export class GitOperationError extends Error {}

export interface GitCommit {
  commitHash: string
  subject: string
}

const BRANCH_PATTERN = /^[A-Za-z0-9._/-]+$/
const HASH_PATTERN = /^[0-9a-fA-F]{7,40}$/
const DEFAULT_LOG_LIMIT = 30
const MAX_LOG_LIMIT = 100

export class ProjectService {
  constructor(
    private projects: ProjectStore,
    private tasks: TaskService,
    private github: GithubClient,
    private workspaceDir: string
  ) {}

  async registerProject(repositoryUrl: string) {
    const parsed = parseGithubUrl(repositoryUrl)

    if (parsed === null) {
      throw new InvalidUrlError("URL must look like https://github.com/{owner}/{repo}")
    }

    let metadata
    try {
      metadata = await this.github.checkAccess(parsed.owner, parsed.repo)
    } catch (error) {
      if (error instanceof RepoNotAccessibleError) {
        throw error
      }
      throw new RepoNotAccessibleError(`Could not reach repository ${parsed.owner}/${parsed.repo}`)
    }

    const existing = await this.projects.findByGithubId(BigInt(metadata.id))

    if (existing !== null) {
      throw new DuplicateProjectError(`Repository ${metadata.owner}/${metadata.name} is already registered`)
    }

    const project = await this.projects.create({
      githubRepositoryId: BigInt(metadata.id),
      repositoryOwner: metadata.owner,
      repositoryName: metadata.name,
      status: "QUEUED",
    })

    const { task, result } = await this.tasks.launch(project.id, `cloning ${metadata.owner}/${metadata.name}`, {
      kind: "clone",
      cloneUrl: metadata.cloneUrl,
      folder: `${metadata.id}-${metadata.owner}-${metadata.name}`,
    })

    if (result.status !== "Succeded") {
      await this.tasks.remove(task.id)
      await this.projects.delete(project.id)
      throw new RepoNotAccessibleError(`Repository ${metadata.owner}/${metadata.name} could not be cloned`)
    }

    return project
  }

  listProjects() {
    return this.projects.list()
  }

  async syncProject(id: number): Promise<StoredProjectDetails> {    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = `${project.githubRepositoryId}-${project.repositoryOwner}-${project.repositoryName}`
    const targetDir = join(this.workspaceDir, folder)
    const hasFiles = existsSync(targetDir) && readdirSync(targetDir).length > 0
    const previousStatus = project.status

    let description: string
    let command: TaskCommand

    if (!hasFiles) {
      description = `cloning ${project.repositoryOwner}/${project.repositoryName}`
      command = {
        kind: "clone",
        cloneUrl: `https://github.com/${project.repositoryOwner}/${project.repositoryName}.git`,
        folder,
      }
    } else if (isDetachedHead(targetDir)) {
      description = `fetching ${project.repositoryOwner}/${project.repositoryName}`
      command = { kind: "fetch", folder }
    } else {
      description = `pulling ${project.repositoryOwner}/${project.repositoryName}`
      command = { kind: "pull", folder }
    }

    const { task, result } = await this.tasks.launch(project.id, description, command)

    if (result.status !== "Succeded") {
      await this.tasks.remove(task.id)
      await this.projects.setStatus(project.id, previousStatus)
      throw new SyncFailedError(`Project ${project.repositoryOwner}/${project.repositoryName} could not be synced`)
    }

    const updated = await this.projects.findById(project.id)

    if (updated === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    return updated
  }

  async listBranches(id: number): Promise<{ branches: string[], currentBranch: string | null, detachedHash: string | null, taskId: number }> {
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)

    const { task, result } = await this.tasks.launch(project.id, `listing branches ${project.repositoryOwner}/${project.repositoryName}`, {
      kind: "list-branches",
      folder,
    })

    if (result.status !== "Succeded") {
      throw new GitOperationError(`Could not list branches for ${project.repositoryOwner}/${project.repositoryName}`)
    }

    const parsed = parseBranchList(result.logTrail ?? "")
    return { branches: parsed.branches, currentBranch: parsed.currentBranch, detachedHash: parsed.detachedHash, taskId: task.id }
  }

  async resolveBranchHash(id: number, branch: string): Promise<{ branch: string, commitHash: string, taskId: number }> {
    const cleanBranch = assertValidBranch(branch)
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)

    const { task, result } = await this.tasks.launch(project.id, `resolving ${cleanBranch} ${project.repositoryOwner}/${project.repositoryName}`, {
      kind: "rev-parse",
      folder,
      branch: cleanBranch,
    })

    if (result.status !== "Succeded") {
      throw new GitOperationError(`Branch ${cleanBranch} does not exist`)
    }

    const commitHash = (result.logTrail ?? "").trim().split("\n").pop()?.trim() ?? ""

    if (HASH_PATTERN.test(commitHash) === false || commitHash.length !== 40) {
      throw new GitOperationError(`Branch ${cleanBranch} does not exist`)
    }

    return { branch: cleanBranch, commitHash: commitHash.toLowerCase(), taskId: task.id }
  }

  async listCommits(
    id: number,
    branch: string,
    limit?: number,
    offset?: number
  ): Promise<{ branch: string, commits: GitCommit[], limit: number, offset: number, taskId: number }> {
    const cleanBranch = assertValidBranch(branch)
    const cleanLimit = assertValidLimit(limit)
    const cleanOffset = assertValidOffset(offset)
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)

    const { task, result } = await this.tasks.launch(project.id, `listing commits ${cleanBranch} ${project.repositoryOwner}/${project.repositoryName}`, {
      kind: "log-commits",
      folder,
      branch: cleanBranch,
      limit: cleanLimit,
      offset: cleanOffset,
    })

    if (result.status !== "Succeded") {
      throw new GitOperationError(`Branch ${cleanBranch} does not exist`)
    }

    return {
      branch: cleanBranch,
      commits: parseCommits(result.logTrail ?? ""),
      limit: cleanLimit,
      offset: cleanOffset,
      taskId: task.id,
    }
  }

  async checkoutBranch(id: number, branch: string): Promise<{ branch: string, taskId: number }> {
    const cleanBranch = assertValidBranch(branch)
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)

    const { task, result } = await this.tasks.launch(project.id, `checking out branch ${cleanBranch} ${project.repositoryOwner}/${project.repositoryName}`, {
      kind: "checkout-branch",
      folder,
      branch: cleanBranch,
    })

    if (result.status !== "Succeded") {
      throw new GitOperationError(`Branch ${cleanBranch} could not be checked out`)
    }

    return { branch: cleanBranch, taskId: task.id }
  }

  async checkoutCommit(id: number, commitHash: string): Promise<{ commitHash: string, taskId: number }> {
    const cleanHash = assertValidHash(commitHash)
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)

    const { task, result } = await this.tasks.launch(project.id, `checking out ${cleanHash} ${project.repositoryOwner}/${project.repositoryName}`, {
      kind: "checkout-detach",
      folder,
      commitHash: cleanHash,
    })

    if (result.status !== "Succeded") {
      throw new GitOperationError(`Commit ${cleanHash} could not be checked out`)
    }

    return { commitHash: cleanHash.toLowerCase(), taskId: task.id }
  }

  private requireWorkspace(project: StoredProjectDetails): string {
    const folder = `${project.githubRepositoryId}-${project.repositoryOwner}-${project.repositoryName}`
    const targetDir = join(this.workspaceDir, folder)

    if (existsSync(targetDir) === false || readdirSync(targetDir).length === 0) {
      throw new WorkspaceMissingError(`Project ${project.repositoryOwner}/${project.repositoryName} has no local checkout`)
    }

    return folder
  }
}

function isDetachedHead(targetDir: string): boolean {
  try {
    const head = readFileSync(join(targetDir, ".git", "HEAD"), "utf8").trim()
    return head.startsWith("ref: ") === false
  } catch {
    return false
  }
}

function assertValidBranch(branch: string): string {  const trimmed = branch.trim()

  if (trimmed.length === 0 || trimmed.length > 255 || BRANCH_PATTERN.test(trimmed) === false) {
    throw new InvalidGitRequestError("Branch must use letters, numbers, dot, underscore, slash or dash")
  }

  if (trimmed.includes("..") || trimmed.includes("--") || trimmed.startsWith("-") || trimmed.startsWith("/") || trimmed.startsWith(".")) {
    throw new InvalidGitRequestError("Branch is not valid")
  }

  if (trimmed.includes("@{") || trimmed.includes("~") || trimmed.includes("^") || trimmed.includes(":") || trimmed.includes("?") || trimmed.includes("*") || trimmed.includes("[") || trimmed.includes("\\")) {
    throw new InvalidGitRequestError("Branch is not valid")
  }

  return trimmed
}

function assertValidHash(commitHash: string): string {
  const trimmed = commitHash.trim()

  if (HASH_PATTERN.test(trimmed) === false) {
    throw new InvalidGitRequestError("Commit hash must be 7 to 40 hex characters")
  }

  return trimmed
}

function assertValidLimit(limit?: number): number {
  if (limit === undefined) {
    return DEFAULT_LOG_LIMIT
  }

  if (Number.isInteger(limit) === false || limit < 1 || limit > MAX_LOG_LIMIT) {
    throw new InvalidGitRequestError("Limit must be an integer between 1 and 100")
  }

  return limit
}

function assertValidOffset(offset?: number): number {
  if (offset === undefined) {
    return 0
  }

  if (Number.isInteger(offset) === false || offset < 0) {
    throw new InvalidGitRequestError("Offset must be an integer equal or greater than 0")
  }

  return offset
}

function parseBranchList(output: string): { branches: string[], currentBranch: string | null, detachedHash: string | null } {
  const branches: string[] = []
  let currentBranch: string | null = null
  let detachedHash: string | null = null

  for (const line of output.split("\n")) {
    const trimmed = line.trim()

    if (trimmed.length === 0) {
      continue
    }

    const isCurrent = trimmed.startsWith("* ")
    const withoutMarker = isCurrent ? trimmed.slice(2) : trimmed

    if (withoutMarker.includes("->")) {
      continue
    }

    const detached = withoutMarker.match(/^\((HEAD detached|no branch)(?:, .*?)? (?:at|from) ([0-9a-fA-F]+)\)$/)

    if (detached !== null) {
      if (isCurrent) {
        detachedHash = (detached[2] as string).toLowerCase()
      }
      continue
    }

    if (withoutMarker.startsWith("(")) {
      continue
    }

    const remote = withoutMarker.match(/^remotes\/[^/]+\/(.+)$/)
    const name = (remote?.[1] ?? withoutMarker).trim()

    if (name.length === 0 || branches.includes(name)) {
      continue
    }

    branches.push(name)

    if (isCurrent && remote === null) {
      currentBranch = name
    }
  }

  return { branches, currentBranch, detachedHash }
}

function parseCommits(output: string): GitCommit[] {
  const commits: GitCommit[] = []

  for (const line of output.split("\n")) {
    if (line.trim().length === 0) {
      continue
    }

    const tab = line.indexOf("\t")

    if (tab <= 0) {
      continue
    }

    const commitHash = line.slice(0, tab).trim()
    const subject = line.slice(tab + 1).trim()

    if (/^[0-9a-fA-F]{40}$/.test(commitHash) === false) {
      continue
    }

    commits.push({ commitHash: commitHash.toLowerCase(), subject })
  }

  return commits
}

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs"
import { join, resolve, sep } from "node:path"
import { GithubClient, RepoNotAccessibleError, parseGithubUrl } from "../../infrastructure/github-client/github.client.js"
import { TaskService } from "../task/task.service.js"
import { taskOutput, type TaskCommand } from "../../infrastructure/task-runner/task.runner.js"
import type { StoredAgentExecution } from "../agent-execution/agent-execution.repository.js"
import type { PipelineExecutions, ProjectArchitectureExecutions } from "../agent-execution/agent-execution.service.js"
import type { ProjectStore, StoredProjectDetails } from "./project.repository.js"
import { projectWorkspaceFolder } from "./project-workspace.js"
export { ANALYZER_AGENT_TYPE } from "../agent-settings/agent-types.js"

export class InvalidUrlError extends Error {}
export class DuplicateProjectError extends Error {}
export class ProjectNotFoundError extends Error {}
export class SyncFailedError extends Error {}
export class InvalidGitRequestError extends Error {}
export class WorkspaceMissingError extends Error {}
export class GitOperationError extends Error {}
export class ProjectFileError extends Error {}
export class AnalysisAlreadyRunningError extends Error {}
export class AnalysisInProgressError extends Error {}
export class SyncInProgressError extends Error {}

export interface GitCommit {
  commitHash: string
  subject: string
}

const BRANCH_PATTERN = /^[A-Za-z0-9._/-]+$/
const HASH_PATTERN = /^[0-9a-fA-F]{7,40}$/
const DEFAULT_LOG_LIMIT = 30
const MAX_LOG_LIMIT = 100
const MAX_FILE_BYTES = 512 * 1024

export const ANALYSIS_EVALUATION_TYPE = "Analysis"

/** Opens a pipeline run for an evaluation. Satisfied by AgentExecutionService. */
export interface AnalysisRunner {
  openPipelineForProject(projectId: number, branch: string, commitHash: string): Promise<AnalysisRequest>
  openProjectArchitecturePipelineForProject(projectId: number, branch: string, commitHash: string): Promise<ProjectArchitectureAnalysisRequest>
}

export interface AnalysisRequest {
  versionId: number
  evaluationId: number
  execution: StoredAgentExecution
  executions: PipelineExecutions
}

export interface ProjectArchitectureAnalysisRequest {
  versionId: number
  evaluationId: number
  executions: ProjectArchitectureExecutions
}

export interface VersionAnalysis {
  id: number
  branch: string | null
  commitHash: string | null
  analysisStatus: string
  analyzedAt: Date | null
  evaluationId: number | null
  execution: StoredAgentExecution | null
  executions: StoredAgentExecution[]
  derivedStatus: string
}

export class ProjectService {
  constructor(
    private projects: ProjectStore,
    private tasks: TaskService,
    private github: GithubClient,
    private workspaceDir: string,
    private analyses: AnalysisRunner
  ) {}

  async registerProject(repositoryUrl: string, shallowClone = false) {
    const parsed = parseGithubUrl(repositoryUrl)

    if (parsed === null) {
      throw new InvalidUrlError("URL must look like https://github.com/{owner}/{repo} or git@github.com:{owner}/{repo}.git")
    }

    let metadata: { id: number; owner: string; name: string; cloneUrl: string } | null = null
    if (parsed.protocol === "https") {
      try {
        metadata = await this.github.checkAccess(parsed.owner, parsed.repo)
      } catch (error) {
        if (error instanceof RepoNotAccessibleError) {
          throw error
        }
        throw new RepoNotAccessibleError(`Could not reach repository ${parsed.owner}/${parsed.repo}`)
      }
    }

    const owner = metadata?.owner ?? parsed.owner
    const name = metadata?.name ?? parsed.repo
    const githubRepositoryId = metadata === null ? null : BigInt(metadata.id)
    const existing = await this.projects.findByRepo(owner, name) ?? (githubRepositoryId === null ? null : await this.projects.findByGithubId(githubRepositoryId))

    if (existing !== null) {
      throw new DuplicateProjectError(`Repository ${owner}/${name} is already registered`)
    }

    const project = await this.projects.create({
      githubRepositoryId,
      cloneProtocol: parsed.protocol,
      shallowClone,
      repositoryOwner: owner,
      repositoryName: name,
      status: "QUEUED",
    })

    const { task, result } = await this.tasks.launch(project.id, `cloning ${owner}/${name}`, {
      kind: "clone",
      cloneUrl: parsed.protocol === "ssh" ? `git@github.com:${owner}/${name}.git` : `https://github.com/${owner}/${name}.git`,
      folder: projectWorkspaceFolder({ ...project, githubRepositoryId }),
      shallowClone,
    })

    if (result.status !== "Succeded") {
      await this.tasks.remove(task.id)
      await this.projects.delete(project.id)
      throw new RepoNotAccessibleError(`Repository ${owner}/${name} could not be cloned`)
    }

    return project
  }

  listProjects() {
    return this.projects.list()
  }

  async syncProject(id: number): Promise<StoredProjectDetails> {
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    // A sync rewrites the checkout a running pipeline is reading.
    const open = await this.projects.findAnyOpenExecution(project.id)

    if (open !== null) {
      throw new AnalysisInProgressError(
        `Project ${project.repositoryOwner}/${project.repositoryName} is already being analyzed (execution ${open.id})`
      )
    }

    const folder = projectWorkspaceFolder(project)
    const targetDir = join(this.workspaceDir, folder)
    const hasFiles = existsSync(targetDir) && readdirSync(targetDir).length > 0
    const previousStatus = project.status

    let description: string
    let command: TaskCommand

    if (!hasFiles) {
      description = `cloning ${project.repositoryOwner}/${project.repositoryName}`
      command = {
        kind: "clone",
        cloneUrl: project.cloneProtocol === "ssh"
          ? `git@github.com:${project.repositoryOwner}/${project.repositoryName}.git`
          : `https://github.com/${project.repositoryOwner}/${project.repositoryName}.git`,
        folder,
        shallowClone: project.shallowClone,
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

    const parsed = parseBranchList(taskOutput(result))
    return { branches: parsed.branches, currentBranch: parsed.currentBranch, detachedHash: parsed.detachedHash, taskId: task.id }
  }

  async listTree(id: number): Promise<{ files: string[], taskId: number }> {
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)

    const { task, result } = await this.tasks.launch(project.id, `listing files ${project.repositoryOwner}/${project.repositoryName}`, {
      kind: "list-tree",
      folder,
    })

    if (result.status !== "Succeded") {
      throw new GitOperationError(`Could not list the files of ${project.repositoryOwner}/${project.repositoryName}`)
    }

    return { files: parseFiles(taskOutput(result)), taskId: task.id }
  }

  async readFile(id: number, requestPath: string): Promise<{ path: string, content: string, size: number }> {
    const cleanPath = assertValidFilePath(requestPath)
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const folder = this.requireWorkspace(project)
    const targetDir = join(this.workspaceDir, folder)
    const resolved = resolve(targetDir, cleanPath)

    if (resolved !== targetDir && !resolved.startsWith(targetDir + sep)) {
      throw new InvalidGitRequestError("Path must stay inside the project checkout")
    }

    let stat: { isFile: () => boolean, size: number }
    try {
      const found = statSync(resolved)
      if (!found.isFile()) {
        throw new ProjectFileError(`Path ${cleanPath} is not a file`)
      }
      stat = found
    } catch (error) {
      if (error instanceof ProjectFileError) {
        throw error
      }
      throw new ProjectFileError(`File ${cleanPath} does not exist`)
    }

    if (stat.size > MAX_FILE_BYTES) {
      throw new ProjectFileError("File is too large to preview")
    }

    const buffer = readFileSync(resolved)

    if (buffer.includes(0)) {
      throw new ProjectFileError("File is not a text file")
    }

    return { path: cleanPath, content: buffer.toString("utf8"), size: stat.size }
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

    const commitHash = taskOutput(result).trim().split("\n").pop()?.trim() ?? ""

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
      commits: parseCommits(taskOutput(result)),
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

  /**
   * Runs the architecture-audit pipeline on the selected version: the version
   * row is saved (or reused), it becomes the selected one, a fresh evaluation
   * is created, and both agents are started in the background. The executions
   * come back Waiting; the pipeline reports each stage afterwards.
   */
  async analyzeProject(id: number, branch: string, commitHash: string): Promise<AnalysisRequest> {
    const cleanBranch = assertValidBranch(branch)
    const cleanHash = assertValidHash(commitHash).toLowerCase()
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    // An analysis reads the checkout a running sync is rewriting. The runner
    // marks the project SYNCING while the sync task is in flight.
    if (project.status === "SYNCING") {
      throw new SyncInProgressError(
        `Project ${project.repositoryOwner}/${project.repositoryName} is already syncing`
      )
    }

    this.requireWorkspace(project)

    const running = await this.projects.findOpenExecution(project.id, cleanHash)

    if (running !== null) {
      throw new AnalysisAlreadyRunningError(
        `Version ${cleanBranch} at ${cleanHash.slice(0, 7)} is already being analyzed (execution ${running.id})`
      )
    }

    return this.analyses.openPipelineForProject(project.id, cleanBranch, cleanHash)
  }

  /**
   * Runs the project-architecture pipeline on the selected version: same
   * guards and version handling as analyzeProject, but three stage rows
   * (orientation, architecture, semantic_validation) under one evaluation.
   * The executions come back Waiting; the pipeline reports each stage
   * afterwards.
   */
  async analyzeProjectArchitecture(id: number, branch: string, commitHash: string): Promise<ProjectArchitectureAnalysisRequest> {
    const cleanBranch = assertValidBranch(branch)
    const cleanHash = assertValidHash(commitHash).toLowerCase()
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    if (project.status === "SYNCING") {
      throw new SyncInProgressError(
        `Project ${project.repositoryOwner}/${project.repositoryName} is already syncing`
      )
    }

    this.requireWorkspace(project)

    const running = await this.projects.findOpenExecution(project.id, cleanHash)

    if (running !== null) {
      throw new AnalysisAlreadyRunningError(
        `Version ${cleanBranch} at ${cleanHash.slice(0, 7)} is already being analyzed (execution ${running.id})`
      )
    }

    return this.analyses.openProjectArchitecturePipelineForProject(project.id, cleanBranch, cleanHash)
  }

  async listVersions(id: number): Promise<VersionAnalysis[]> {
    const project = await this.projects.findById(id)

    if (project === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    const versions = await this.projects.listVersions(project.id)

    return versions.map((version) => {
      const executions = version.executions.map((execution) => ({ ...execution, status: execution.status as StoredAgentExecution["status"] }))
      const execution = executions.find((execution) => execution.agentType === "analyzer") ?? executions[0] ?? null
      return {
        id: version.id,
        branch: version.branch,
        commitHash: version.commitHash,
        analysisStatus: version.analysisStatus,
        analyzedAt: version.analyzedAt,
        evaluationId: version.evaluation?.id ?? null,
        execution,
        executions,
        derivedStatus: deriveStatus(version.evaluation, version.executions),
      }
    })
  }

  private requireWorkspace(project: StoredProjectDetails): string {
    const folder = projectWorkspaceFolder(project)
    const targetDir = join(this.workspaceDir, folder)

    if (existsSync(targetDir) === false || readdirSync(targetDir).length === 0) {
      throw new WorkspaceMissingError(`Project ${project.repositoryOwner}/${project.repositoryName} has no local checkout`)
    }

    return folder
  }
}

/** One status for a version with two pipeline rows: an open run wins, then any
 *  failure, then completion only when every row completed. */
function deriveStatus(
  evaluation: { id: number } | null,
  executions: Array<{ status: string }>,
): string {
  const open = executions.find((execution) => execution.status === "Running")
    ?? executions.find((execution) => execution.status === "Waiting")

  if (open !== undefined) {
    return open.status
  }

  if (executions.some((execution) => execution.status === "Failed")) {
    return "Failed"
  }

  if (executions.length > 0 && executions.every((execution) => execution.status === "Completed")) {
    return "Completed"
  }

  return evaluation === null ? "NeverAnalyzed" : "Pending"
}

function isDetachedHead(targetDir: string): boolean {
  try {
    const head = readFileSync(join(targetDir, ".git", "HEAD"), "utf8").trim()
    return head.startsWith("ref: ") === false
  } catch {
    return false
  }
}

function assertValidFilePath(requestPath: string): string {
  const trimmed = requestPath.trim().replace(/\\/g, "/")

  if (trimmed.length === 0 || trimmed.length > 1024 || trimmed.includes("\0")) {
    throw new InvalidGitRequestError("Path must be a relative file path")
  }

  const segments = trimmed.split("/")

  if (segments.some((segment) => segment === "" || segment === "." || segment === "..")) {
    throw new InvalidGitRequestError("Path must stay inside the project checkout")
  }

  if (segments[0] === ".git") {
    throw new InvalidGitRequestError("Path must stay inside the project checkout")
  }

  return segments.join("/")
}

function assertValidBranch(branch: string): string {
  const trimmed = branch.trim()

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

function parseFiles(output: string): string[] {
  const files: string[] = []

  for (const line of output.split("\n")) {
    const trimmed = line.trim()

    if (trimmed.length === 0) {
      continue
    }

    files.push(trimmed.replace(/\\/g, "/"))
  }

  return files
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

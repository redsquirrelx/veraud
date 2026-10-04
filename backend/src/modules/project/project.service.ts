import { existsSync, readdirSync } from "node:fs"
import { join } from "node:path"
import { GithubClient, RepoNotAccessibleError, parseGithubUrl } from "../../infrastructure/github-client/github.client.js"
import type { TaskStore } from "../task/task.repository.js"
import type { TaskQueue } from "../../infrastructure/task-runner/task.runner.js"
import type { ProjectStore, StoredProjectDetails } from "./project.repository.js"

export class InvalidUrlError extends Error {}
export class DuplicateProjectError extends Error {}
export class ProjectNotFoundError extends Error {}
export class SyncFailedError extends Error {}

export class ProjectService {
  constructor(
    private projects: ProjectStore,
    private tasks: TaskStore,
    private github: GithubClient,
    private runner: TaskQueue,
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

    const task = await this.tasks.create({
      projectId: project.id,
      description: `cloning ${metadata.owner}/${metadata.name}`,
      status: "Queued",
    })
    const result = await this.runner.enqueue({
      taskId: task.id,
      projectId: project.id,
      command: {
        kind: "clone",
        cloneUrl: metadata.cloneUrl,
        folder: `${metadata.id}-${metadata.owner}-${metadata.name}`,
      },
    })

    if (result.status !== "Succeded") {
      await this.tasks.delete(task.id)
      await this.projects.delete(project.id)
      throw new RepoNotAccessibleError(`Repository ${metadata.owner}/${metadata.name} could not be cloned`)
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

    const folder = `${project.githubRepositoryId}-${project.repositoryOwner}-${project.repositoryName}`
    const targetDir = join(this.workspaceDir, folder)
    const hasFiles = existsSync(targetDir) && readdirSync(targetDir).length > 0
    const previousStatus = project.status

    const task = await this.tasks.create({
      projectId: project.id,
      description: hasFiles
        ? `pulling ${project.repositoryOwner}/${project.repositoryName}`
        : `cloning ${project.repositoryOwner}/${project.repositoryName}`,
      status: "Queued",
    })

    const result = hasFiles
      ? await this.runner.enqueue({ taskId: task.id, projectId: project.id, command: { kind: "pull", folder } })
      : await this.runner.enqueue({
          taskId: task.id,
          projectId: project.id,
          command: {
            kind: "clone",
            cloneUrl: `https://github.com/${project.repositoryOwner}/${project.repositoryName}.git`,
            folder,
          },
        })

    if (result.status !== "Succeded") {
      await this.tasks.delete(task.id)
      await this.projects.setStatus(project.id, previousStatus)
      throw new SyncFailedError(`Project ${project.repositoryOwner}/${project.repositoryName} could not be synced`)
    }

    const updated = await this.projects.findById(project.id)

    if (updated === null) {
      throw new ProjectNotFoundError(`Project ${id} does not exist`)
    }

    return updated
  }
}

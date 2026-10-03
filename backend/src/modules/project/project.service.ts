import { GithubClient, RepoNotAccessibleError, parseGithubUrl } from "../../infrastructure/github-client/github.client.js"
import type { TaskStore } from "../task/task.repository.js"
import type { CloneRunner } from "../../infrastructure/task-runner/task.runner.js"
import type { ProjectStore } from "./project.repository.js"

export class InvalidUrlError extends Error {}
export class DuplicateProjectError extends Error {}

export class ProjectService {
  constructor(
    private projects: ProjectStore,
    private tasks: TaskStore,
    private github: GithubClient,
    private runner: CloneRunner
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
    const result = await this.runner.enqueueClone(
      task.id,
      project.id,
      metadata.cloneUrl,
      `${metadata.id}-${metadata.owner}-${metadata.name}`
    )

    if (result.status !== "Succeded") {
      await this.tasks.delete(task.id)
      await this.projects.delete(project.id)
      throw new RepoNotAccessibleError(`Repository ${metadata.owner}/${metadata.name} could not be cloned`)
    }

    return project
  }
}

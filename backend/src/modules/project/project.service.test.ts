import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { GithubClient, RepoNotAccessibleError } from "../../infrastructure/github-client/github.client.js"
import type { CloneResult, CloneRunner } from "../../infrastructure/task-runner/task.runner.js"
import type {
  NewProject,
  ProjectStore,
  StoredProject,
} from "./project.repository.js"
import type { NewTask, StoredTask, TaskStore } from "../task/task.repository.js"
import {
  DuplicateProjectError,
  InvalidUrlError,
  ProjectService,
} from "./project.service.js"

const storedTask: StoredTask = {
  id: 9,
  projectId: 7,
  repositoryOwner: "octocat",
  repositoryName: "Hello-World",
  description: "cloning octocat/Hello-World",
  status: "Queued",
  exitCode: null,
}

function makeFakes(options: {
  existing?: StoredProject | null
  githubId?: number
  clone?: CloneResult
} = {}) {
  const calls = { enqueued: 0, deletedTasks: [] as Array<number>, deletedProjects: [] as Array<number> }

  const projects: ProjectStore & { created: Array<NewProject> } = {
    created: [],
    async create(data: NewProject): Promise<StoredProject> {
      this.created.push(data)
      return { id: 7, repositoryOwner: "octocat", repositoryName: "Hello-World", status: "QUEUED" }
    },
    async findByGithubId(): Promise<StoredProject | null> {
      return options.existing ?? null
    },
    async delete(id: number): Promise<void> {
      calls.deletedProjects.push(id)
    },
    async setStatus(): Promise<void> {},
    async markSynced(): Promise<void> {},
    async list() {
      return []
    },
  }

  const tasks: TaskStore & { created: Array<NewTask> } = {
    created: [],
    async create(data: NewTask): Promise<StoredTask> {
      this.created.push(data)
      return { ...storedTask, projectId: data.projectId, status: data.status }
    },
    async update(): Promise<StoredTask> {
      throw new Error("not used here")
    },
    async delete(id: number): Promise<void> {
      calls.deletedTasks.push(id)
    },
    async findById(): Promise<StoredTask | null> {
      return null
    },
    async findActive(): Promise<StoredTask[]> {
      return []
    },
  }

  const github = new GithubClient()
  github.checkAccess = async () => ({
    id: options.githubId ?? 1296269,
    owner: "octocat",
    name: "Hello-World",
    cloneUrl: "https://github.com/octocat/Hello-World.git",
  })

  const runner: CloneRunner = {
    async enqueueClone(): Promise<CloneResult> {
      calls.enqueued += 1
      return options.clone ?? { status: "Succeded", exitCode: 0, logTrail: "" }
    },
  }

  const service = new ProjectService(projects, tasks, github, runner)
  return { service, projects, tasks, calls }
}

describe("ProjectService.registerProject", () => {
  it("creates a QUEUED project once its clone succeeds", async () => {
    const { service, projects, tasks, calls } = makeFakes()

    const project = await service.registerProject("https://github.com/octocat/Hello-World")

    assert.equal(project.id, 7)
    assert.deepEqual(projects.created, [{
      githubRepositoryId: BigInt(1296269),
      repositoryOwner: "octocat",
      repositoryName: "Hello-World",
      status: "QUEUED",
    }])
    assert.equal(calls.enqueued, 1)
    assert.deepEqual(tasks.created, [{
      projectId: 7,
      description: "cloning octocat/Hello-World",
      status: "Queued",
    }])
    assert.deepEqual(calls.deletedProjects, [])
    assert.deepEqual(calls.deletedTasks, [])
  })

  it("rolls back when the clone fails", async () => {
    const { service, projects, calls } = makeFakes({
      clone: { status: "Failed", exitCode: 1, logTrail: "fatal" },
    })

    await assert.rejects(
      service.registerProject("https://github.com/octocat/Hello-World"),
      RepoNotAccessibleError
    )
    assert.equal(projects.created.length, 1)
    assert.deepEqual(calls.deletedTasks, [9])
    assert.deepEqual(calls.deletedProjects, [7])
  })

  it("rejects malformed urls", async () => {
    const { service } = makeFakes()

    await assert.rejects(service.registerProject("not-a-url"), InvalidUrlError)
  })

  it("rejects already registered repositories", async () => {
    const { service } = makeFakes({
      existing: { id: 3, repositoryOwner: "octocat", repositoryName: "Hello-World", status: "QUEUED" },
    })

    await assert.rejects(
      service.registerProject("https://github.com/octocat/Hello-World"),
      DuplicateProjectError
    )
  })

  it("wraps unexpected github failures as access errors without persisting", async () => {
    const failing = new GithubClient()
    failing.checkAccess = async () => {
      throw new Error("boom")
    }
    const service = new ProjectService(
      {
        create: async () => { throw new Error("must not persist") },
        findByGithubId: async () => null,
        delete: async () => { throw new Error("must not delete") },
        setStatus: async () => { throw new Error("must not set status") },
        markSynced: async () => { throw new Error("must not mark synced") },
        list: async () => [],
      },
      {
        create: async () => { throw new Error("must not create tasks") },
        update: async () => { throw new Error("must not update") },
        delete: async () => { throw new Error("must not delete tasks") },
        findById: async () => null,
        findActive: async () => [],
      },
      failing,
      { enqueueClone: async () => { throw new Error("must not enqueue") } }
    )

    await assert.rejects(
      service.registerProject("https://github.com/octocat/Hello-World"),
      /Could not reach repository/
    )
  })
})

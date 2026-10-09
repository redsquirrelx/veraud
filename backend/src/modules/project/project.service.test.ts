import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { GithubClient, RepoNotAccessibleError } from "../../infrastructure/github-client/github.client.js"
import type { QueuedTask, TaskQueue, TaskResult, GitCommand } from "../../infrastructure/task-runner/task.runner.js"
import type {
  NewProject,
  ProjectStore,
  StoredProject,
  StoredProjectDetails,
} from "./project.repository.js"
import type { NewTask, StoredTask, TaskStore } from "../task/task.repository.js"
import { TaskService } from "../task/task.service.js"
import {
  DuplicateProjectError,
  InvalidUrlError,
  ProjectNotFoundError,
  ProjectService,
  SyncFailedError,
} from "./project.service.js"

const storedTask: StoredTask = {
  id: 9,
  projectId: 7,
  repositoryOwner: "octocat",
  repositoryName: "Hello-World",
  description: "cloning octocat/Hello-World",
  status: "Queued",
  kind: "clone",
  exitCode: null,
}

function makeFakes(options: {
  existing?: StoredProject | null
  details?: StoredProjectDetails | null
  githubId?: number
  clone?: TaskResult
} = {}) {
  const calls = { enqueued: 0, commands: [] as Array<GitCommand>, deletedTasks: [] as Array<number>, deletedProjects: [] as Array<number>, statuses: [] as Array<{ id: number; status: string }> }

  const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-svc-"))
  const projects: ProjectStore & { created: Array<NewProject> } = {
    created: [],
    async create(data: NewProject): Promise<StoredProject> {
      this.created.push(data)
      return { id: 7, repositoryOwner: "octocat", repositoryName: "Hello-World", status: "QUEUED" }
    },
    async findByGithubId(): Promise<StoredProject | null> {
      return options.existing ?? null
    },
    async findById(): Promise<StoredProjectDetails | null> {
      return options.details ?? null
    },
    async delete(id: number): Promise<void> {
      calls.deletedProjects.push(id)
    },
    async setStatus(id: number, status: string): Promise<void> {
      calls.statuses.push({ id, status })
    },
    async markSynced(): Promise<void> {},
    async list() {
      return []
    },
    async upsertVersion(): Promise<never> {
      throw new Error("not used here")
    },
    async setSelectedVersion(): Promise<void> {
      throw new Error("not used here")
    },
    async createEvaluation(): Promise<never> {
      throw new Error("not used here")
    },
    async listVersions() {
      return []
    },
    async findOpenExecution() {
      return null
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

  const runner: TaskQueue = {
    async enqueue(task: QueuedTask): Promise<TaskResult> {
      calls.enqueued += 1
      calls.commands.push(task.command)
      return options.clone ?? { status: "Succeded", exitCode: 0, logTrail: "" }
    },
  }

  const service = new ProjectService(projects, new TaskService(tasks, runner), github, workspaceDir, {
    open: async () => { throw new Error("not used here") },
  })
  return { service, projects, tasks, calls, workspaceDir }
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
    assert.deepEqual(calls.commands, [{
      kind: "clone",
      cloneUrl: "https://github.com/octocat/Hello-World.git",
      folder: "1296269-octocat-Hello-World",
    }])
    assert.deepEqual(tasks.created, [{
      projectId: 7,
      description: "cloning octocat/Hello-World",
      status: "Queued",
      kind: "clone",
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
        findById: async () => null,
        delete: async () => { throw new Error("must not delete") },
        setStatus: async () => { throw new Error("must not set status") },
        markSynced: async () => { throw new Error("must not mark synced") },
        list: async () => [],
        upsertVersion: async () => { throw new Error("must not upsert versions") },
        setSelectedVersion: async () => { throw new Error("must not select versions") },
        createEvaluation: async () => { throw new Error("must not create evaluations") },
        listVersions: async () => { throw new Error("must not list versions") },
        findOpenExecution: async () => { throw new Error("must not search executions") },
      },
      new TaskService(
        {
          create: async () => { throw new Error("must not create tasks") },
          update: async () => { throw new Error("must not update") },
          delete: async () => { throw new Error("must not delete tasks") },
          findById: async () => null,
          findActive: async () => [],
        },
        { enqueue: async () => { throw new Error("must not enqueue") } }
      ),
      failing,
      join(tmpdir(), "veraud-unused"),
      { open: async () => { throw new Error("must not open executions") } }
    )

    await assert.rejects(
      service.registerProject("https://github.com/octocat/Hello-World"),
      /Could not reach repository/
    )
  })
})

describe("ProjectService.syncProject", () => {
  const details: StoredProjectDetails = {
    id: 7,
    githubRepositoryId: BigInt(1296269),
    repositoryOwner: "octocat",
    repositoryName: "Hello-World",
    status: "READY",
    registeredAt: new Date("2026-01-02T03:04:05.000Z"),
    lastSyncedAt: null,
    branch: null,
    commitHash: null,
  }

  it("pulls when the workspace already has files", async () => {
    const { service, calls, workspaceDir } = makeFakes({ details })
    const folder = join(workspaceDir, "1296269-octocat-Hello-World")
    mkdirSync(join(folder, ".git"), { recursive: true })
    writeFileSync(join(folder, ".git", "HEAD"), "ref: refs/heads/main\n")
    writeFileSync(join(folder, "file.txt"), "hello")

    const synced = await service.syncProject(7)

    assert.equal(synced.id, 7)
    assert.deepEqual(calls.commands, [{ kind: "pull", folder: "1296269-octocat-Hello-World" }])
    assert.deepEqual(calls.deletedProjects, [])
  })

  it("fetches without moving HEAD when detached", async () => {
    const { service, calls, tasks, workspaceDir } = makeFakes({ details })
    const folder = join(workspaceDir, "1296269-octocat-Hello-World")
    mkdirSync(join(folder, ".git"), { recursive: true })
    writeFileSync(join(folder, ".git", "HEAD"), `${"a".repeat(40)}\n`)
    writeFileSync(join(folder, "file.txt"), "hello")

    const synced = await service.syncProject(7)

    assert.equal(synced.id, 7)
    assert.deepEqual(calls.commands, [{ kind: "fetch", folder: "1296269-octocat-Hello-World" }])
    assert.deepEqual(tasks.created.map((created) => created.description), ["fetching octocat/Hello-World"])
  })

  it("clones when the workspace is empty", async () => {
    const { service, calls } = makeFakes({ details })

    const synced = await service.syncProject(7)

    assert.equal(synced.id, 7)
    assert.deepEqual(calls.commands, [{
      kind: "clone",
      cloneUrl: "https://github.com/octocat/Hello-World.git",
      folder: "1296269-octocat-Hello-World",
    }])
  })

  it("rejects unknown projects", async () => {
    const { service } = makeFakes()

    await assert.rejects(service.syncProject(99), ProjectNotFoundError)
  })

  it("restores the previous status when sync fails", async () => {
    const { service, calls, workspaceDir } = makeFakes({
      details,
      clone: { status: "Failed", exitCode: 1, logTrail: "fatal" },
    })
    const folder = join(workspaceDir, "1296269-octocat-Hello-World")
    mkdirSync(folder, { recursive: true })
    writeFileSync(join(folder, "file.txt"), "hello")

    await assert.rejects(service.syncProject(7), SyncFailedError)
    assert.deepEqual(calls.deletedTasks, [9])
    assert.deepEqual(calls.statuses, [{ id: 7, status: "READY" }])
  })
})

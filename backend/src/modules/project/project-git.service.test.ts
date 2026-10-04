import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { GithubClient } from "../../infrastructure/github-client/github.client.js"
import type { QueuedTask, TaskQueue, TaskResult } from "../../infrastructure/task-runner/task.runner.js"
import type { StoredProjectDetails } from "./project.repository.js"
import type { NewTask, StoredTask } from "../task/task.repository.js"
import { GitOperationError, InvalidGitRequestError, ProjectNotFoundError, ProjectService, WorkspaceMissingError } from "./project.service.js"

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

function makeService(options: {
  details?: StoredProjectDetails | null
  result?: TaskResult
  withWorkspace?: boolean
} = {}) {
  const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-gitsvc-"))
  const folder = "1296269-octocat-Hello-World"

  if (options.withWorkspace === true) {
    const target = join(workspaceDir, folder)
    mkdirSync(target, { recursive: true })
    writeFileSync(join(target, "file.txt"), "hello")
  }

  const enqueued: Array<QueuedTask> = []
  const created: Array<NewTask> = []
  let taskId = 0

  const service = new ProjectService(
    {
      create: async () => { throw new Error("not used") },
      findByGithubId: async () => null,
      findById: async () => options.details === undefined ? details : options.details,
      delete: async () => {},
      setStatus: async () => { throw new Error("must not touch project status") },
      markSynced: async () => { throw new Error("must not mark synced") },
      list: async () => [],
    },
    {
      create: async (data: NewTask): Promise<StoredTask> => {
        taskId += 1
        created.push(data)
        return { id: taskId, projectId: data.projectId, repositoryOwner: "octocat", repositoryName: "Hello-World", description: data.description, status: data.status, exitCode: null }
      },
      update: async () => { throw new Error("not used") },
      delete: async () => { throw new Error("must not delete tasks") },
      findById: async () => null,
      findActive: async () => [],
    },
    new GithubClient(),
    {
      enqueue: async (task: QueuedTask): Promise<TaskResult> => {
        enqueued.push(task)
        return options.result ?? { status: "Succeded", exitCode: 0, logTrail: "" }
      },
    } as TaskQueue,
    workspaceDir
  )

  return { service, enqueued, created }
}

describe("ProjectService git commands", () => {
  it("lists branches parsing the star marker", async () => {
    const { service, enqueued } = makeService({
      withWorkspace: true,
      result: { status: "Succeded", exitCode: 0, logTrail: "* main\n  feature\n" },
    })

    const result = await service.listBranches(7)

    assert.deepEqual(result.branches, ["main", "feature"])
    assert.equal(result.taskId, 1)
    assert.deepEqual(enqueued, [{ taskId: 1, projectId: 7, command: { kind: "list-branches", folder: "1296269-octocat-Hello-World" } }])
  })

  it("resolves a branch hash trimming newlines", async () => {
    const hash = "a".repeat(40)
    const { service } = makeService({
      withWorkspace: true,
      result: { status: "Succeded", exitCode: 0, logTrail: `${hash}\n` },
    })

    const result = await service.resolveBranchHash(7, "main")

    assert.equal(result.commitHash, hash)
    assert.equal(result.branch, "main")
  })

  it("lists commits paginated parsing hash and subject", async () => {
    const first = "a".repeat(40)
    const second = "b".repeat(40)
    const { service, enqueued } = makeService({
      withWorkspace: true,
      result: { status: "Succeded", exitCode: 0, logTrail: `${first}\tfirst subject\n${second}\tsecond\n` },
    })

    const result = await service.listCommits(7, "main", 2, 0)

    assert.deepEqual(result.commits, [
      { commitHash: first, subject: "first subject" },
      { commitHash: second, subject: "second" },
    ])
    assert.equal(result.limit, 2)
    assert.equal(result.offset, 0)
    assert.deepEqual(enqueued[0]?.command, { kind: "log-commits", folder: "1296269-octocat-Hello-World", branch: "main", limit: 2, offset: 0 })
  })

  it("checks out a hash lowering case", async () => {
    const hash = "A".repeat(40)
    const { service } = makeService({ withWorkspace: true })

    const result = await service.checkoutCommit(7, hash)

    assert.equal(result.commitHash, hash.toLowerCase())
  })

  it("rejects invalid branches without creating tasks", async () => {
    const { service, created } = makeService({ withWorkspace: true })

    await assert.rejects(service.resolveBranchHash(7, "main; rm -rf"), InvalidGitRequestError)
    await assert.rejects(service.listCommits(7, "--help", 10, 0), InvalidGitRequestError)
    await assert.rejects(service.listCommits(7, "main", 101, 0), InvalidGitRequestError)
    await assert.rejects(service.checkoutCommit(7, "xyz"), InvalidGitRequestError)
    assert.deepEqual(created, [])
  })

  it("keeps tasks on git failure and maps to 422 errors", async () => {
    const { service } = makeService({
      withWorkspace: true,
      result: { status: "Failed", exitCode: 1, logTrail: "fatal: bad" },
    })

    await assert.rejects(service.listBranches(7), GitOperationError)
    await assert.rejects(service.checkoutCommit(7, "a".repeat(40)), GitOperationError)
  })

  it("rejects missing workspaces without enqueueing", async () => {
    const { service, enqueued } = makeService({})

    await assert.rejects(service.listBranches(7), WorkspaceMissingError)
    assert.deepEqual(enqueued, [])
  })

  it("rejects unknown projects", async () => {
    const { service } = makeService({ details: null, withWorkspace: true })

    await assert.rejects(service.listBranches(99), ProjectNotFoundError)
  })
})

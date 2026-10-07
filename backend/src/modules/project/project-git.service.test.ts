import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { GithubClient } from "../../infrastructure/github-client/github.client.js"
import type { QueuedTask, TaskQueue, TaskResult } from "../../infrastructure/task-runner/task.runner.js"
import type { StoredProjectDetails } from "./project.repository.js"
import type { NewTask, StoredTask } from "../task/task.repository.js"
import { TaskService } from "../task/task.service.js"
import { GitOperationError, InvalidGitRequestError, ProjectFileError, ProjectNotFoundError, ProjectService, WorkspaceMissingError } from "./project.service.js"

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
    new TaskService(
      {
        create: async (data: NewTask): Promise<StoredTask> => {
          taskId += 1
          created.push(data)
          return { id: taskId, projectId: data.projectId, repositoryOwner: "octocat", repositoryName: "Hello-World", description: data.description, status: data.status, kind: data.kind, exitCode: null }
        },
        update: async () => { throw new Error("not used") },
        delete: async () => { throw new Error("must not delete tasks") },
        findById: async () => null,
        findActive: async () => [],
      },
      {
        enqueue: async (task: QueuedTask): Promise<TaskResult> => {
          enqueued.push(task)
          return options.result ?? { status: "Succeded", exitCode: 0, logTrail: "" }
        },
      } as TaskQueue
    ),
    new GithubClient(),
    workspaceDir
  )

  return { service, enqueued, created, workspaceDir }
}

describe("ProjectService git commands", () => {
  it("lists branches parsing local and remote names once", async () => {
    const { service, enqueued } = makeService({
      withWorkspace: true,
      result: { status: "Succeded", exitCode: 0, logTrail: "* main\n  remotes/origin/HEAD -> origin/main\n  remotes/origin/feature\n" },
    })

    const result = await service.listBranches(7)

    assert.deepEqual(result.branches, ["main", "feature"])
    assert.equal(result.currentBranch, "main")
    assert.equal(result.detachedHash, null)
    assert.equal(result.taskId, 1)
    assert.deepEqual(enqueued, [{ taskId: 1, projectId: 7, command: { kind: "list-branches", folder: "1296269-octocat-Hello-World" } }])
  })

  it("reports a detached HEAD with its hash", async () => {
    const { service } = makeService({
      withWorkspace: true,
      result: { status: "Succeded", exitCode: 0, logTrail: "* (HEAD detached at abc1234)\n  main\n  remotes/origin/feature\n" },
    })

    const result = await service.listBranches(7)

    assert.deepEqual(result.branches, ["main", "feature"])
    assert.equal(result.currentBranch, null)
    assert.equal(result.detachedHash, "abc1234")
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

  it("lists the tracked files at HEAD", async () => {
    const { service, enqueued, created } = makeService({
      withWorkspace: true,
      result: { status: "Succeded", exitCode: 0, logTrail: "src/app.py\nsrc\nREADME.md\n\n" },
    })

    const result = await service.listTree(7)

    assert.deepEqual(result.files, ["src/app.py", "src", "README.md"])
    assert.equal(result.taskId, 1)
    assert.deepEqual(enqueued, [{ taskId: 1, projectId: 7, command: { kind: "list-tree", folder: "1296269-octocat-Hello-World" } }])
    assert.deepEqual(created.map((entry) => entry.description), ["listing files octocat/Hello-World"])
  })

  it("maps a failed tree listing to a git error", async () => {
    const { service } = makeService({ withWorkspace: true, result: { status: "Failed", exitCode: 1, logTrail: "fatal" } })

    await assert.rejects(service.listTree(7), GitOperationError)
  })

  it("reads a file from the workspace checkout", async () => {
    const { service, enqueued } = makeService({ withWorkspace: true })

    const result = await service.readFile(7, "file.txt")

    assert.deepEqual(result, { path: "file.txt", content: "hello", size: 5 })
    assert.deepEqual(enqueued, [])
  })

  it("reads a nested file normalizing the path", async () => {
    const { service, workspaceDir } = makeService({ withWorkspace: true })
    mkdirSync(join(workspaceDir, "1296269-octocat-Hello-World", "src"), { recursive: true })
    writeFileSync(join(workspaceDir, "1296269-octocat-Hello-World", "src", "app.ts"), "export {}\n")

    const result = await service.readFile(7, "src\\app.ts")

    assert.equal(result.path, "src/app.ts")
    assert.equal(result.content, "export {}\n")
  })

  it("rejects traversal, absolute and git paths without touching the runner", async () => {
    const { service, enqueued } = makeService({ withWorkspace: true })

    for (const path of ["../secret.txt", "..", "/etc/passwd", ".git/HEAD", "", "src/../../x"]) {
      await assert.rejects(service.readFile(7, path), InvalidGitRequestError)
    }
    assert.deepEqual(enqueued, [])
  })

  it("rejects missing files, directories and binary content", async () => {
    const { service, workspaceDir } = makeService({ withWorkspace: true })
    mkdirSync(join(workspaceDir, "1296269-octocat-Hello-World", "empty"), { recursive: true })
    writeFileSync(join(workspaceDir, "1296269-octocat-Hello-World", "blob.bin"), Buffer.from([0x89, 0x00, 0xff]))

    await assert.rejects(service.readFile(7, "nope.txt"), ProjectFileError)
    await assert.rejects(service.readFile(7, "empty"), ProjectFileError)
    await assert.rejects(service.readFile(7, "blob.bin"), ProjectFileError)
  })

  it("rejects unknown projects when reading files", async () => {
    const { service } = makeService({ details: null, withWorkspace: true })

    await assert.rejects(service.readFile(99, "file.txt"), ProjectNotFoundError)
  })

  it("checks out a branch attaching HEAD", async () => {
    const { service, enqueued } = makeService({ withWorkspace: true })

    const result = await service.checkoutBranch(7, "feature")

    assert.deepEqual(result, { branch: "feature", taskId: 1 })
    assert.deepEqual(enqueued, [{ taskId: 1, projectId: 7, command: { kind: "checkout-branch", folder: "1296269-octocat-Hello-World", branch: "feature" } }])
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

import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import type { FastifyBaseLogger } from "fastify"
import { logger } from "../../config/logger.js"
import type { StoredTask, TaskStore } from "../../modules/task/task.repository.js"
import { TaskRunner } from "./task.runner.js"

const quiet = { child: () => ({ info() {}, warn() {}, error() {}, debug() {} }) }
logger.configure(quiet as unknown as FastifyBaseLogger)

function makeStore() {
  const stored: StoredTask = {
    id: 1,
    projectId: 2,
    repositoryOwner: "acme",
    repositoryName: "Demo",
    description: "git task",
    status: "Queued",
    kind: "list-branches",
    exitCode: null,
  }
  const statuses: Array<{ id: number, status: string }> = []
  const synced: Array<{ id: number }> = []
  const store: TaskStore = {
    create: async () => stored,
    update: async (_id, data) => ({ ...stored, ...data }),
    delete: async () => {},
    findById: async () => stored,
    findActive: async () => [],
  }
  const projects = {
    setStatus: async (id: number, status: string) => {
      statuses.push({ id, status })
    },
    markSynced: async (id: number) => {
      synced.push({ id })
    },
  }
  return { store, projects, statuses, synced }
}

function makeRepo(): { workspace: string, folder: string, mainHash: string, featureHash: string } {
  const workspace = mkdtempSync(join(tmpdir(), "veraud-git-"))
  const source = join(mkdtempSync(join(tmpdir(), "veraud-src-")), "repo")
  execSync(`git init -q -b main "${source}"`)
  execSync(`git -C "${source}" config user.email t@t`)
  execSync(`git -C "${source}" config user.name t`)
  writeFileSync(join(source, "file.txt"), "one")
  execSync(`git -C "${source}" add .`)
  execSync(`git -C "${source}" commit -qm first`)
  execSync(`git -C "${source}" checkout -qb feature`)
  writeFileSync(join(source, "file.txt"), "two")
  execSync(`git -C "${source}" commit -qam second`)
  execSync(`git -C "${source}" checkout -q main`)
  const folder = "clone"
  execSync(`git clone -q "${source}" "${join(workspace, folder)}"`)
  const mainHash = execSync(`git -C "${join(workspace, folder)}" rev-parse main`).toString().trim()
  const featureHash = execSync(`git -C "${source}" rev-parse feature`).toString().trim()
  return { workspace, folder, mainHash, featureHash }
}

describe("TaskRunner git commands", () => {
  it("lists local branches without touching project status", async () => {
    const { workspace, folder } = makeRepo()
    const { store, projects, statuses, synced } = makeStore()
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "list-branches", folder } })

    assert.equal(result.status, "Succeded")
    assert.match(result.logTrail ?? "", /main/)
    assert.match(result.logTrail ?? "", /feature/)
    assert.deepEqual(statuses, [])
    assert.deepEqual(synced, [])
  })

  it("resolves a branch hash without touching project status", async () => {
    const { workspace, folder, mainHash } = makeRepo()
    const { store, projects, statuses } = makeStore()
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "rev-parse", folder, branch: "main" } })

    assert.equal(result.status, "Succeded")
    assert.equal((result.logTrail ?? "").trim().split("\n").pop()?.trim(), mainHash)
    assert.deepEqual(statuses, [])
  })

  it("lists commits with pagination", async () => {
    const { workspace, folder } = makeRepo()
    const { store, projects } = makeStore()
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const first = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "log-commits", folder, branch: "main", limit: 1, offset: 0 } })
    const second = await runner.enqueue({ taskId: 2, projectId: 2, command: { kind: "log-commits", folder, branch: "main", limit: 10, offset: 1 } })

    assert.equal(first.status, "Succeded")
    assert.equal((first.logTrail ?? "").trim().split("\n").length, 1)
    assert.equal(second.status, "Succeded")
    assert.equal((second.logTrail ?? "").trim(), "")
  })

  it("checks out a commit detached with force", async () => {
    const { workspace, folder, mainHash } = makeRepo()
    const { store, projects, statuses, synced } = makeStore()
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "checkout-detach", folder, commitHash: mainHash } })

    assert.equal(result.status, "Succeded")
    assert.equal(execSync(`git -C "${join(workspace, folder)}" rev-parse HEAD`).toString().trim(), mainHash)
    assert.deepEqual(statuses, [])
    assert.deepEqual(synced, [])
  })

  it("re-attaches a detached HEAD by checking out a branch", async () => {
    const { workspace, folder, mainHash } = makeRepo()
    const { store, projects, statuses, synced } = makeStore()
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const detached = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "checkout-detach", folder, commitHash: mainHash } })
    assert.equal(detached.status, "Succeded")

    const attached = await runner.enqueue({ taskId: 2, projectId: 2, command: { kind: "checkout-branch", folder, branch: "feature" } })

    assert.equal(attached.status, "Succeded")
    assert.equal(execSync(`git -C "${join(workspace, folder)}" symbolic-ref --short HEAD`).toString().trim(), "feature")
    assert.deepEqual(statuses, [])
    assert.deepEqual(synced, [])
  })

  it("fails cleanly for unknown branches", async () => {
    const { workspace, folder } = makeRepo()
    const { store, projects } = makeStore()
    const runner = new TaskRunner(store, projects, { broadcast: () => {} }, workspace)

    const result = await runner.enqueue({ taskId: 1, projectId: 2, command: { kind: "rev-parse", folder, branch: "nope" } })

    assert.equal(result.status, "Failed")
    assert.equal(result.exitCode, 1)
  })
})

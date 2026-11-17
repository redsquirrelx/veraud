import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs"
import { join as joinPath } from "node:path"
import { tmpdir } from "node:os"
import { ProjectService, type AnalysisRunner } from "../project/project.service.js"
import type { GithubClient } from "../../infrastructure/github-client/github.client.js"
import type { TaskService } from "../task/task.service.js"
import type { ProjectStore, StoredProjectDetails } from "../project/project.repository.js"
import { projectWorkspaceFolder } from "../project/project-workspace.js"

const projectDetails: StoredProjectDetails = {
  id: 1,
  githubRepositoryId: null,
  cloneProtocol: "https",
  shallowClone: false,
  repositoryOwner: "acme",
  repositoryName: "shop",
  status: "READY",
  registeredAt: new Date(),
  lastSyncedAt: null,
  branch: "main",
  commitHash: null,
}

function makeService(workspaceDir: string) {
  const store = {
    findById: async () => projectDetails,
    findByRepo: async () => projectDetails,
    findByGithubId: async () => null,
    list: async () => [projectDetails],
    upsertVersion: async () => { throw new Error("not used") },
    setSelectedVersion: async () => {},
    create: async () => ({ id: 1, repositoryOwner: "acme", repositoryName: "shop", status: "READY" }),
    delete: async () => {},
    setStatus: async () => {},
    markSynced: async () => {},
    recordSync: async () => {},
    listSyncRecords: async () => [],
    findSyncRecord: async () => null,
  } as unknown as ProjectStore
  return new ProjectService(store, {} as TaskService, {} as GithubClient, workspaceDir, {} as AnalysisRunner)
}

function git(checkout: string, ...args: string[]): string {
  return execFileSync("git", ["--no-replace-objects", ...args], { cwd: checkout, encoding: "utf8" }).trim()
}

describe("project verification commits", () => {
  it("lists strict descendants of the baseline and never the baseline itself", async () => {
    const workspaceDir = mkdtempSync(joinPath(tmpdir(), "veraud-commits-"))
    const checkout = joinPath(workspaceDir, projectWorkspaceFolder(projectDetails))
    mkdirSync(checkout, { recursive: true })
    git(checkout, "init", "-q", "-b", "main")
    git(checkout, "config", "user.name", "Fixture")
    git(checkout, "config", "user.email", "fixture@example.invalid")
    writeFileSync(joinPath(checkout, "a.txt"), "one")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "baseline")
    const baseline = git(checkout, "rev-parse", "HEAD")
    writeFileSync(joinPath(checkout, "b.txt"), "two")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "descendant one")
    writeFileSync(joinPath(checkout, "c.txt"), "three")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "descendant two")
    const service = makeService(workspaceDir)
    const page = await service.verificationCommits(1, baseline, "main", 2, 0)
    assert.deepEqual(page.commits.map((commit) => commit.subject), ["descendant two", "descendant one"])
    assert.equal(page.hasMore, false)
    assert.equal(page.branchTip.length, 40)
    const next = await service.verificationCommits(1, baseline, "main", 1, 0)
    assert.equal(next.commits.length, 1)
    assert.equal(next.hasMore, true)
    const second = await service.verificationCommits(1, baseline, "main", 1, 1)
    assert.deepEqual(second.commits.map((commit) => commit.subject), ["descendant one"])
    assert.equal(second.hasMore, false)
  })

  it("fails explicitly when the baseline does not exist locally", async () => {
    const workspaceDir = mkdtempSync(joinPath(tmpdir(), "veraud-commits-"))
    const checkout = joinPath(workspaceDir, projectWorkspaceFolder(projectDetails))
    mkdirSync(checkout, { recursive: true })
    git(checkout, "init", "-q", "-b", "main")
    const service = makeService(workspaceDir)
    await assert.rejects(service.verificationCommits(1, "a".repeat(40), "main"), /Could not read descendants/)
  })
})

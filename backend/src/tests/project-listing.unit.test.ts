import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { GithubClient } from "../infrastructure/github-client/github.client.js"
import type { ProjectStore, StoredProjectDetails } from "../modules/project/project.repository.js"
import { ProjectService } from "../modules/project/project.service.js"

const withVersion: StoredProjectDetails = {
  id: 1,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  status: "QUEUED",
  registeredAt: new Date("2026-01-02T03:04:05.000Z"),
  lastSyncedAt: new Date("2026-01-03T03:04:05.000Z"),
  branch: "main",
  commitHash: "abc123",
}

const withoutVersion: StoredProjectDetails = {
  id: 2,
  repositoryOwner: "acme",
  repositoryName: "Other",
  status: "QUEUED",
  registeredAt: new Date("2026-02-03T04:05:06.000Z"),
  lastSyncedAt: null,
  branch: null,
  commitHash: null,
}

function serviceWith(rows: StoredProjectDetails[]) {
  const projects: ProjectStore = {
    create: async () => { throw new Error("not used here") },
    findByGithubId: async () => null,
    delete: async () => {},
    setStatus: async () => {},
    markSynced: async () => {},
    list: async () => rows,
  }
  return new ProjectService(projects, null as never, new GithubClient(), null as never)
}

describe("project listing unit", () => {
  it("returns every project with its selected version", async () => {
    const service = serviceWith([withVersion, withoutVersion])

    assert.deepEqual(await service.listProjects(), [withVersion, withoutVersion])
  })

  it("returns an empty list when nothing is registered", async () => {
    const service = serviceWith([])

    assert.deepEqual(await service.listProjects(), [])
  })
})

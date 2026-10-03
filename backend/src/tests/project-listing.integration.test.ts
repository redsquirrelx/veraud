import { after, before, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import type { AddressInfo } from "node:net"
import { buildApp } from "../app.js"

const backendRoot = fileURLToPath(new URL("../../", import.meta.url))

const noopRunner = {
  enqueueClone: async () => ({ status: "Succeded", exitCode: 0, logTrail: "" }),
}

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-test-"))
  const url = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: backendRoot,
    env: { ...process.env, DATABASE_URL: url },
    stdio: "ignore",
  })
  return url
}

describe("project listing API", () => {
  let baseUrl = ""
  let close = async () => {}

  before(async () => {
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir: mkdtempSync(join(tmpdir(), "veraud-ws-")),
      silent: true,
      makeRunner: () => noopRunner,
    })

    const versioned = await db.project.create({
      data: {
        githubRepositoryId: BigInt(111),
        repositoryOwner: "acme",
        repositoryName: "Demo",
        status: "QUEUED",
      },
    })
    const version = await db.projectVersion.create({
      data: { projectId: versioned.id, branch: "main", commitHash: "abc123", analysisStatus: "COMPLETED" },
    })
    await db.project.update({
      where: { id: versioned.id },
      data: { selectedVersionId: version.id },
    })
    await db.project.create({
      data: {
        githubRepositoryId: BigInt(222),
        repositoryOwner: "acme",
        repositoryName: "Other",
        status: "QUEUED",
      },
    })

    await app.listen({ port: 0, host: "127.0.0.1" })
    const address = app.server.address() as AddressInfo
    baseUrl = `http://127.0.0.1:${address.port}`
    close = async () => {
      await app.close()
      await db.$disconnect()
    }
  })

  after(async () => {
    await close()
  })

  it("lists projects with branch and commit when present", async () => {
    const response = await fetch(`${baseUrl}/api/projects`)

    assert.equal(response.status, 200)
    const projects = (await response.json()) as Array<{
      id: number
      repositoryOwner: string
      repositoryName: string
      status: string
      registeredAt: string
      branch: string | null
      commitHash: string | null
    }>

    assert.equal(projects.length, 2)
    assert.equal(projects[0]?.repositoryName, "Demo")
    assert.equal(projects[0]?.branch, "main")
    assert.equal(projects[0]?.commitHash, "abc123")
    assert.equal(typeof projects[0]?.registeredAt, "string")
    assert.equal(projects[1]?.repositoryName, "Other")
    assert.equal(projects[1]?.branch, null)
    assert.equal(projects[1]?.commitHash, null)
  })
})

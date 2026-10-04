import { after, before, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import type { AddressInfo } from "node:net"
import { buildApp } from "../app.js"

const backendRoot = fileURLToPath(new URL("../../", import.meta.url))

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

describe("project sync API", () => {
  let baseUrl = ""
  let workspaceDir = ""
  let close = async () => {}

  before(async () => {
    workspaceDir = mkdtempSync(join(tmpdir(), "veraud-ws-"))
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
    })

    const project = await db.project.create({
      data: {
        githubRepositoryId: BigInt(777),
        repositoryOwner: "acme",
        repositoryName: "Demo",
        status: "READY",
      },
    })
    assert.equal(project.id, 1)

    const source = join(mkdtempSync(join(tmpdir(), "veraud-src-")), "repo")
    execSync(`git init -q -b main "${source}"`)
    writeFileSync(join(source, "file.txt"), "hello")
    execSync(`git -C "${source}" add .`)
    execSync(`git -C "${source}" -c user.email=t@t -c user.name=t commit -qm init`)
    execSync(`git clone -q "${source}" "${join(workspaceDir, "777-acme-Demo")}"`)

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

  it("pulls an existing checkout and returns the updated project", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/sync`, { method: "POST" })

    assert.equal(response.status, 200)
    const project = (await response.json()) as {
      id: number
      repositoryOwner: string
      repositoryName: string
      status: string
      lastSyncedAt: string | null
    }

    assert.equal(project.id, 1)
    assert.equal(project.status, "READY")
    assert.equal(typeof project.lastSyncedAt, "string")
  })

  it("rejects unknown projects with 404", async () => {
    const response = await fetch(`${baseUrl}/api/projects/999/sync`, { method: "POST" })

    assert.equal(response.status, 404)
  })

  it("rejects non-numeric ids with 400", async () => {
    const response = await fetch(`${baseUrl}/api/projects/abc/sync`, { method: "POST" })

    assert.equal(response.status, 400)
  })
})

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

describe("project git API", () => {
  let baseUrl = ""
  let close = async () => {}
  let mainHash = ""

  before(async () => {
    const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-ws-"))
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir,
      silent: true,
    })

    await db.project.create({
      data: {
        githubRepositoryId: BigInt(778),
        repositoryOwner: "acme",
        repositoryName: "GitDemo",
        status: "READY",
      },
    })

    const source = join(mkdtempSync(join(tmpdir(), "veraud-src-")), "repo")
    execSync(`git init -q -b main "${source}"`)
    execSync(`git -C "${source}" config user.email t@t`)
    execSync(`git -C "${source}" config user.name t`)
    writeFileSync(join(source, "file.txt"), "one")
    execSync(`git -C "${source}" add .`)
    execSync(`git -C "${source}" commit -qm first`)
    writeFileSync(join(source, "file.txt"), "two")
    execSync(`git -C "${source}" commit -qam second`)
    execSync(`git -C "${source}" checkout -qb feature`)
    writeFileSync(join(source, "file.txt"), "three")
    writeFileSync(join(source, "feature.txt"), "feature only")
    execSync(`git -C "${source}" add .`)
    execSync(`git -C "${source}" commit -qm third`)
    execSync(`git -C "${source}" checkout -q main`)
    execSync(`git clone -q "${source}" "${join(workspaceDir, "778-acme-GitDemo")}"`)
    mainHash = execSync(`git -C "${join(workspaceDir, "778-acme-GitDemo")}" rev-parse HEAD`).toString().trim()

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

  it("lists remote-only branches too", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/git/branches`, { method: "POST" })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { branches: string[], currentBranch: string | null, detachedHash: string | null, taskId: number }

    assert.ok(body.branches.includes("main"))
    assert.ok(body.branches.includes("feature"))
    assert.equal(body.currentBranch, "main")
    assert.equal(body.detachedHash, null)
    assert.equal(typeof body.taskId, "number")
  })

  it("resolves a branch hash via a task", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/git/rev-parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: "main" }),
    })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { branch: string, commitHash: string, taskId: number }

    assert.equal(body.branch, "main")
    assert.equal(body.commitHash, mainHash)
  })

  it("lists commits paginated", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/git/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: "main", limit: 1, offset: 1 }),
    })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { branch: string, commits: Array<{ commitHash: string, subject: string }>, limit: number, offset: number }

    assert.equal(body.commits.length, 1)
    assert.equal(body.commits[0]?.subject, "first")
    assert.equal(body.limit, 1)
    assert.equal(body.offset, 1)
  })

  it("checks out a commit detached with force", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/git/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ commitHash: mainHash }),
    })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { commitHash: string, taskId: number }

    assert.equal(body.commitHash, mainHash)
  })

  it("re-attaches HEAD by checking out a branch", async () => {
    const detached = await fetch(`${baseUrl}/api/projects/1/git/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ commitHash: mainHash }),
    })
    assert.equal(detached.status, 200)

    const whileDetached = await fetch(`${baseUrl}/api/projects/1/git/branches`, { method: "POST" })
    const detachedState = (await whileDetached.json()) as { branches: string[], currentBranch: string | null, detachedHash: string | null }

    assert.equal(detachedState.currentBranch, null)
    assert.ok(detachedState.detachedHash !== null && mainHash.startsWith(detachedState.detachedHash))
    assert.ok(detachedState.branches.includes("main"))

    const response = await fetch(`${baseUrl}/api/projects/1/git/checkout-branch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: "feature" }),
    })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { branch: string, taskId: number }

    assert.equal(body.branch, "feature")

    const listed = await fetch(`${baseUrl}/api/projects/1/git/branches`, { method: "POST" })
    const state = (await listed.json()) as { currentBranch: string | null, detachedHash: string | null }

    assert.equal(state.currentBranch, "feature")
    assert.equal(state.detachedHash, null)

    const log = await fetch(`${baseUrl}/api/projects/1/git/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: "feature", limit: 1 }),
    })

    assert.equal(log.status, 200)
    const commits = (await log.json()) as { commits: Array<{ commitHash: string, subject: string }> }

    assert.equal(commits.commits[0]?.subject, "third")
  })

  it("lists the files tracked at HEAD", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/git/tree`, { method: "POST" })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { files: string[], taskId: number }

    assert.ok(body.files.includes("file.txt"))
    assert.equal(typeof body.taskId, "number")
  })

  it("follows the checkout when listing files again", async () => {
    const mainFiles = await (await fetch(`${baseUrl}/api/projects/1/git/tree`, { method: "POST" })).json() as { files: string[] }
    assert.ok(mainFiles.files.includes("file.txt"))

    const moved = await fetch(`${baseUrl}/api/projects/1/git/checkout-branch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: "feature" }),
    })
    assert.equal(moved.status, 200)

    const featureFiles = await (await fetch(`${baseUrl}/api/projects/1/git/tree`, { method: "POST" })).json() as { files: string[] }

    assert.ok(featureFiles.files.includes("feature.txt"))
  })

  it("rejects invalid branches with 400 without creating side effects", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/git/rev-parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ branch: "bad;branch" }),
    })

    assert.equal(response.status, 400)
  })

  it("reads a text file from the workspace checkout", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: "file.txt" }),
    })

    assert.equal(response.status, 200)
    const body = (await response.json()) as { path: string, content: string, size: number }

    assert.equal(body.path, "file.txt")
    assert.equal(typeof body.content, "string")
    assert.ok(body.content.length > 0)
    assert.equal(body.size, Buffer.byteLength(body.content, "utf8"))
  })

  it("rejects traversal paths with 400", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: "../secret.txt" }),
    })

    assert.equal(response.status, 400)
  })

  it("rejects missing files with 422", async () => {
    const response = await fetch(`${baseUrl}/api/projects/1/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: "nope.txt" }),
    })

    assert.equal(response.status, 422)
  })

  it("rejects unknown projects with 404", async () => {
    const response = await fetch(`${baseUrl}/api/projects/999/git/branches`, { method: "POST" })

    assert.equal(response.status, 404)
  })
})

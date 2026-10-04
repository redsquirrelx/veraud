import { after, before, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import type { AddressInfo } from "node:net"
import { buildApp } from "./app.js"

const realFetch = globalThis.fetch
const backendRoot = fileURLToPath(new URL("../", import.meta.url))

function mockGithubApi(status: number, body: unknown) {
  globalThis.fetch = (async (...args: Parameters<typeof fetch>) => {
    if (String(args[0]).includes("api.github.com")) {
      return new Response(JSON.stringify(body), { status })
    }
    return realFetch(...args)
  }) as typeof fetch
}

function restoreFetch() {
  globalThis.fetch = realFetch
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

const noopRunner = {
  enqueueClone: async () => ({ status: "Succeded", exitCode: 0, logTrail: "" }),
}

describe("projects API with mocked github", () => {
  let baseUrl = ""
  let close = async () => {}

  before(async () => {
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir: mkdtempSync(join(tmpdir(), "veraud-ws-")),
      silent: true,
      makeRunner: () => noopRunner,
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
    restoreFetch()
    await close()
  })

  it("registers a project and enqueues its task", async () => {
    mockGithubApi(200, { id: 555001, name: "Demo", clone_url: "https://github.com/acme/Demo.git" })

    const response = await fetch(`${baseUrl}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repositoryUrl: "https://github.com/acme/Demo" }),
    })

    assert.equal(response.status, 201)
    assert.deepEqual(await response.json(), {
      id: 1,
      repositoryOwner: "acme",
      repositoryName: "Demo",
      status: "QUEUED",
    })

    const active = (await (await fetch(`${baseUrl}/api/tasks/active`)).json()) as Array<object>
    assert.equal(active.length, 1)
  })

  it("rejects malformed urls with 400", async () => {
    const response = await fetch(`${baseUrl}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repositoryUrl: "not-a-url" }),
    })

    assert.equal(response.status, 400)
  })

  it("rejects duplicates with 409", async () => {
    mockGithubApi(200, { id: 555001, name: "Demo", clone_url: "https://github.com/acme/Demo.git" })

    const body = JSON.stringify({ repositoryUrl: "https://github.com/acme/Demo" })

    await fetch(`${baseUrl}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    })

    const retry = await fetch(`${baseUrl}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    })

    assert.equal(retry.status, 409)
  })

  it("rejects inaccessible repos with 422", async () => {
    mockGithubApi(404, { message: "Not Found" })

    const response = await fetch(`${baseUrl}/api/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repositoryUrl: "https://github.com/acme/Gone" }),
    })

    assert.equal(response.status, 422)
  })
})

describe("projects API with the real github api", () => {
  it("clones and streams task events over ws", { timeout: 120_000 }, async () => {
    restoreFetch()

    const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-ws-"))
    const { app, db } = await buildApp({ databaseUrl: freshDatabase(), workspaceDir, silent: true })

    await app.listen({ port: 0, host: "127.0.0.1" })

    const address = app.server.address() as AddressInfo
    const baseUrl = `http://127.0.0.1:${address.port}`

    const events: Array<{ task: { status: string } }> = []
    const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`)

    await new Promise<void>((resolve) => socket.addEventListener("open", () => resolve(), { once: true }))
    
    socket.addEventListener("message", (event) => {
      events.push(JSON.parse(String(event.data)) as { task: { status: string } })
    })

    try {
      const response = await fetch(`${baseUrl}/api/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repositoryUrl: "https://github.com/octocat/Hello-World" }),
      })

      assert.equal(response.status, 201)

      const deadline = Date.now() + 90_000
      while (Date.now() < deadline) {
        const done = events.some((event) => event.task.status === "Succeded")
        if (done) {
          break
        }
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }

      const statuses = events.map((event) => event.task.status)
      assert.equal(statuses[0], "Queued")
      assert.ok(statuses.includes("Running"), `expected Running, got ${statuses}`)
      assert.ok(statuses.includes("Succeded"), `expected Succeded, got ${statuses}`)

      const active = (await (await fetch(`${baseUrl}/api/tasks/active`)).json()) as Array<unknown>
      assert.equal(active.length, 0)

      const finished = await db.task.findFirst({ where: { status: "Succeded" } })
      assert.ok(finished, "expected a finished task row")
      assert.equal(finished?.description, "cloning octocat/Hello-World")
      assert.ok((finished?.logTrail ?? "").length > 0, "expected the clone log to be saved")

      const synced = await db.project.findFirst({ where: { repositoryName: "Hello-World" } })
      assert.ok(synced?.lastSyncedAt instanceof Date, "expected lastSyncedAt to be saved")
    } finally {
      socket.close()
      await app.close()
      await db.$disconnect()
    }
  })
})

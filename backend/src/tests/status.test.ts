import { afterEach, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { createServer } from "node:http"
import type { AddressInfo } from "node:net"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
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

const noopRunner = {
  enqueue: async () => ({ status: "Succeded", exitCode: 0, logTrail: "" }),
}

describe("status endpoint", () => {
  let dbs: Array<{ close: () => Promise<void> }> = []

  afterEach(async () => {
    for (const db of dbs) {
      await db.close()
    }
    dbs = []
  })

  async function start(options?: { agentServerUrl?: string }) {
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir: mkdtempSync(join(tmpdir(), "veraud-ws-")),
      silent: true,
      makeRunner: () => noopRunner,
      ...options,
    })
    dbs.push({ close: async () => { await app.close(); await db.$disconnect() } })
    return app
  }

  it("reports the agent server online", async () => {
    const agent = createServer((_request, response) => {
      response.writeHead(200, { "Content-Type": "application/json" })
      response.end(JSON.stringify({ status: "ok" }))
    })
    await new Promise<void>((resolve) => agent.listen(0, "127.0.0.1", resolve))
    const port = (agent.address() as AddressInfo).port

    try {
      const app = await start({ agentServerUrl: `http://127.0.0.1:${port}` })
      const response = await app.inject({ method: "GET", url: "/status" })

      assert.equal(response.statusCode, 200)
      assert.deepEqual(response.json(), { status: "ok", service: "backend", agentServer: "online" })
    } finally {
      await new Promise<void>((resolve) => agent.close(() => resolve()))
    }
  })

  it("reports the agent server offline", async () => {
    const app = await start({ agentServerUrl: "http://127.0.0.1:1" })
    const response = await app.inject({ method: "GET", url: "/status" })

    assert.deepEqual(response.json(), { status: "ok", service: "backend", agentServer: "offline" })
  })

  it("reports unknown without a configured url", async () => {
    const app = await start()
    const response = await app.inject({ method: "GET", url: "/status" })

    assert.deepEqual(response.json(), { status: "ok", service: "backend", agentServer: "unknown" })
  })
})

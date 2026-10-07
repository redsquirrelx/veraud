import { after, before, describe, it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import type { AddressInfo } from "node:net"
import { buildApp } from "../../app.js"

const backendRoot = fileURLToPath(new URL("../../../", import.meta.url))

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-ai-test-"))
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

describe("ai providers API", () => {
  let baseUrl = ""
  let close = async () => {}

  before(async () => {
    const { app, db } = await buildApp({
      databaseUrl: freshDatabase(),
      workspaceDir: mkdtempSync(join(tmpdir(), "veraud-ai-ws-")),
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
    await close()
  })

  it("seeds OpenAI, Anthropic and Google", async () => {
    const response = await fetch(`${baseUrl}/api/ai-providers`)
    const providers = await response.json() as Array<{ name: string }>

    assert.equal(response.status, 200)
    assert.deepEqual(providers.map((provider) => provider.name), ["Anthropic", "Google", "OpenAI"])
  })

  it("allows browser deletes through CORS", async () => {
    const preflight = await fetch(`${baseUrl}/api/ai-providers/1/models/1`, {
      method: "OPTIONS",
      headers: { Origin: "http://localhost:7500", "Access-Control-Request-Method": "DELETE" },
    })

    assert.ok((preflight.headers.get("access-control-allow-methods") ?? "").includes("DELETE"))
  })

  it("manages models scoped by provider", async () => {
    const providers = await (await fetch(`${baseUrl}/api/ai-providers`)).json() as Array<{ id: number, name: string }>
    const openai = providers.find((provider) => provider.name === "OpenAI")
    assert.ok(openai)

    const created = await fetch(`${baseUrl}/api/ai-providers/${openai?.id}/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "gpt-4o" }),
    })
    assert.equal(created.status, 201)

    const duplicate = await fetch(`${baseUrl}/api/ai-providers/${openai?.id}/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "gpt-4o" }),
    })
    assert.equal(duplicate.status, 409)

    const invalid = await fetch(`${baseUrl}/api/ai-providers/${openai?.id}/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "bad name!" }),
    })
    assert.equal(invalid.status, 400)

    const missing = await fetch(`${baseUrl}/api/ai-providers/9999/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "gpt-4o" }),
    })
    assert.equal(missing.status, 404)

    const detail = await (await fetch(`${baseUrl}/api/ai-providers/${openai?.id}`)).json() as { models: Array<{ id: number, name: string, inUse: boolean }> }
    assert.deepEqual(detail.models.map((model) => model.name), ["gpt-4o"])
    assert.deepEqual(detail.models.map((model) => model.inUse), [false])

    const modelId = detail.models[0]?.id
    assert.ok(modelId)

    const removed = await fetch(`${baseUrl}/api/ai-providers/${openai?.id}/models/${modelId}`, { method: "DELETE" })
    assert.equal(removed.status, 204)

    const retry = await fetch(`${baseUrl}/api/ai-providers/${openai?.id}/models/${modelId}`, { method: "DELETE" })
    assert.equal(retry.status, 404)
  })

  it("manages credentials without ever exposing the full key", async () => {
    const providers = await (await fetch(`${baseUrl}/api/ai-providers`)).json() as Array<{ id: number, name: string }>
    const google = providers.find((provider) => provider.name === "Google")
    assert.ok(google)

    const createdResponse = await fetch(`${baseUrl}/api/ai-providers/${google?.id}/credentials`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "prod", apiKey: "secret-1234" }),
    })
    const created = await createdResponse.json() as { id: number, name: string, apiKeyPreview: string, inUse: boolean }
    assert.equal(createdResponse.status, 201)
    assert.equal(created.apiKeyPreview, "****1234")
    assert.equal(created.inUse, false)
    assert.ok(!("apiKey" in created))

    const listed = await (await fetch(`${baseUrl}/api/ai-providers/${google?.id}`)).json() as { credentials: Array<{ name: string, apiKeyPreview: string, inUse: boolean, apiKey?: string }> }
    assert.equal(listed.credentials[0]?.apiKeyPreview, "****1234")
    assert.equal(listed.credentials[0]?.inUse, false)
    assert.ok(!("apiKey" in (listed.credentials[0] ?? {})))

    const duplicate = await fetch(`${baseUrl}/api/ai-providers/${google?.id}/credentials`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "prod", apiKey: "other-5678" }),
    })
    assert.equal(duplicate.status, 409)

    const removed = await fetch(`${baseUrl}/api/ai-providers/${google?.id}/credentials/${created.id}`, { method: "DELETE" })
    assert.equal(removed.status, 204)
  })
})

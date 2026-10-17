import { test } from "node:test"
import assert from "node:assert/strict"
import { createServer } from "node:http"
import Fastify from "fastify"
import { logger } from "../../config/logger.js"
import { AgentServerClient } from "./agent-server.client.js"

test("HTTP dispatch sends captured config and access checks do not expose provider errors", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  const requests: Array<{ path: string, body: Record<string, unknown> }> = []
  let denied = false
  let malformed = false
  const server = createServer(async (request, response) => {
    let body = ""
    for await (const chunk of request) body += chunk
    requests.push({ path: request.url!, body: JSON.parse(body) as Record<string, unknown> })
    response.setHeader("content-type", "application/json")
    response.statusCode = denied ? 422 : 200
    response.end(malformed ? "secret-provider-key is not JSON" : JSON.stringify(denied ? { detail: "secret-provider-key" } : request.url?.endsWith("verify-access") ? { verified: true } : request.url?.includes("/pipelines/") ? { analysis: { kind: "library" }, description: { style: "layered" } } : { result: { kind: "library" } }))
  })
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const client = new AgentServerClient(`http://127.0.0.1:${address.port}`)
    const config = { model: { provider: "OpenAI", name: "selected-model", temperature: 0.8, max_tokens: 4096 }, api_key: "secret-provider-key" }
    await client.verify(config)
    assert.deepEqual(await client.run("dummy", { root_path: "checkout" }, 12, config), { kind: "library" })
    assert.deepEqual(requests, [
      { path: "/api/agents/verify-access", body: config },
      { path: "/api/agents/run", body: { agent_type: "dummy", input: { root_path: "checkout" }, execution_id: 12, config } },
    ])
    denied = true
    for (const attempt of [() => client.verify(config), () => client.run("dummy", {}, 13, config)]) {
      await assert.rejects(attempt, (error: unknown) => {
        assert.ok(error instanceof Error)
        assert.doesNotMatch(error.message, /secret-provider-key/)
        return true
      })
    }
    denied = false
    malformed = true
    for (const attempt of [() => client.verify(config), () => client.run("dummy", {}, 14, config)]) {
      await assert.rejects(attempt, (error: unknown) => {
        assert.ok(error instanceof Error)
        assert.doesNotMatch(error.message, /secret-provider-key/)
        return true
      })
    }
  } finally {
    await new Promise<void>((done, reject) => server.close((error) => error ? reject(error) : done()))
    await app.close()
  }
})

test("generic pipeline dispatch posts stage maps to the named pipeline", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  const requests: Array<{ path: string, body: Record<string, unknown> }> = []
  const server = createServer(async (request, response) => {
    let body = ""
    for await (const chunk of request) body += chunk
    requests.push({ path: request.url!, body: JSON.parse(body) as Record<string, unknown> })
    response.setHeader("content-type", "application/json")
    response.statusCode = 200
    response.end(JSON.stringify({ orientation: { summary: "cli" }, architecture: { style: "layered" }, semantic_validation: { verdict: "accepted" } }))
  })
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const client = new AgentServerClient(`http://127.0.0.1:${address.port}`)
    const config = { model: { provider: "OpenAI", name: "selected-model", temperature: 0.8, max_tokens: 4096 }, api_key: "secret-provider-key" }
    const ids = { orientation: 21, architecture: 22, semantic_validation: 23 }
    const configs = { orientation: config, architecture: config, semantic_validation: config }
    assert.deepEqual(
      await client.runPipelineByName("project-architecture", { root_path: "checkout" }, ids, configs),
      { orientation: { summary: "cli" }, architecture: { style: "layered" }, semantic_validation: { verdict: "accepted" } },
    )
    assert.deepEqual(requests, [{
      path: "/api/pipelines/project-architecture/run",
      body: { input: { root_path: "checkout" }, execution_ids: ids, stage_configs: configs },
    }])
    const auditInput = { root_path: "checkout", commit_hash: "a".repeat(40), attributes: ["maintainability"] }
    await client.runPipelineByName("quality-audit", auditInput, { maintainability_manager: 24 }, { maintainability_manager: config })
    assert.deepEqual(requests[1], {
      path: "/api/pipelines/quality-audit/run",
      body: { input: auditInput, execution_ids: { maintainability_manager: 24 },
        stage_configs: { maintainability_manager: config }, timeout_seconds: 1860 },
    }, "audit dispatch must preserve revision/attributes and not inherit the 600s architecture ceiling")
  } finally {
    await new Promise<void>((done, reject) => server.close((error) => error ? reject(error) : done()))
    await app.close()
  }
})

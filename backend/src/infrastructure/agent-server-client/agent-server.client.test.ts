import { test } from "node:test"
import assert from "node:assert/strict"
import { createServer } from "node:http"
import Fastify from "fastify"
import { logger } from "../../config/logger.js"
import { AgentServerClient, AgentTransportError, AuditRunUnavailableError } from "./agent-server.client.js"
import { executionRequest } from "./execution-request.js"
import { AgentCatalogError } from "../../modules/agent-settings/agent-catalog.js"
import { ModelAccessError } from "../../modules/agent-settings/model-access-error.js"

test("access verification distinguishes provider failures without exposing response bodies", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  let status = 503
  const server = createServer((_request, response) => {
    response.writeHead(status, { "content-type": "application/json" })
    response.end(JSON.stringify({ detail: "private-provider-key-and-payload" }))
  })
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const client = new AgentServerClient(`http://127.0.0.1:${address.port}`)
    const config = { model: { provider: "Google", name: "model", temperature: null, max_tokens: null }, api_key: "private-key" }
    for (const [httpStatus, code] of [[403, "access_denied"], [404, "model_not_found"], [422, "invalid_configuration"],
      [429, "rate_limited"], [503, "provider_unavailable"], [504, "timeout"], [502, "verification_failed"]] as const) {
      status = httpStatus
      await assert.rejects(() => client.verify(config), (error: unknown) => {
        assert.ok(error instanceof ModelAccessError)
        assert.equal(error.code, code)
        assert.doesNotMatch(error.message, /private/)
        return true
      })
    }
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()))
    await app.close()
  }
})

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

test("catalog discovery bounds stalled requests and rejects non-JSON responses with a controlled error", async () => {
  let stalled = false
  const server = createServer((_request, response) => {
    if (stalled) return
    response.writeHead(200, { "content-type": "text/plain" })
    response.end("not-json-private-response")
  })
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const url = `http://127.0.0.1:${address.port}`
    for (const timeout of [1000, 30]) {
      stalled = timeout === 30
      const client = new AgentServerClient(url, timeout)
      await assert.rejects(() => client.getAgentCatalog(), (error: unknown) => {
        assert.ok(error instanceof AgentCatalogError)
        assert.doesNotMatch(error.message, /not-json-private-response/)
        return true
      })
    }
  } finally {
    server.closeAllConnections()
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  }
})

test("execution transport waits for delayed headers independently of fetch and bounds a stalled response body", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  let stallBody = false
  const server = createServer(async (_request, response) => {
    await new Promise((resolve) => setTimeout(resolve, 40))
    response.writeHead(200, { "content-type": "application/json" })
    if (stallBody) { response.write('{"result":'); return }
    response.end('{"result":{"done":true}}')
  })
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
  const originalFetch = globalThis.fetch
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const url = `http://127.0.0.1:${address.port}`
    // Long-running POSTs must never fall back to fetch's hidden headers deadline.
    globalThis.fetch = async () => { throw new Error("fetch headers timeout") }
    const config = { model: { provider: "OpenAI", name: "test", temperature: 0, max_tokens: 4000 }, api_key: "private-key" }
    assert.deepEqual(await new AgentServerClient(url, 1000).run("dummy", {}, 1, config), { done: true })
    stallBody = true
    await assert.rejects(() => executionRequest(url, {}, 100), /abort/i)
  } finally {
    globalThis.fetch = originalFetch
    server.closeAllConnections()
    await new Promise<void>((resolve) => server.close(() => resolve()))
    await app.close()
  }
})

test("a socket loss after dispatch is an uncertain outcome, not proof that the agent failed", async () => {
  const app = Fastify({ logger: false })
  logger.configure(app.log)
  const server = createServer(async (request) => {
    await request.toArray() // Consume the accepted execution before dropping the socket.
    request.socket.destroy()
  })
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const url = `http://127.0.0.1:${address.port}`
    const client = new AgentServerClient(url)
    await assert.rejects(() => client.runPipelineByName("quality-audit", { root_path: "checkout" }, {}, {}), (error: unknown) => {
      assert.ok(error instanceof AgentTransportError)
      assert.equal(error.outcomeUncertain, true)
      assert.equal(error.code, "ECONNRESET")
      return true
    })
    await new Promise<void>((resolve) => server.close(() => resolve()))
    await assert.rejects(() => client.runPipelineByName("quality-audit", { root_path: "checkout" }, {}, {}), (error: unknown) => {
      assert.ok(error instanceof AgentTransportError)
      assert.equal(error.outcomeUncertain, false)
      assert.equal(error.code, "ECONNREFUSED")
      return true
    })
  } finally {
    server.closeAllConnections()
    if (server.listening) await new Promise<void>((resolve) => server.close(() => resolve()))
    await app.close()
  }
})

test("reconciliation reads only the existing run and downloads artifacts only after termination", async () => {
  let state = "running"
  const paths: string[] = []
  const server = createServer((request, response) => {
    assert.equal(request.method, "GET", "reconciliation must never replay an execution")
    paths.push(request.url!)
    if (state === "missing") { response.writeHead(404); response.end(); return }
    response.setHeader("content-type", "application/json")
    if (request.url?.endsWith("report.docx")) response.end("PK-document")
    else if (request.url?.endsWith("report")) response.end(JSON.stringify({ identification: { status: "partial" } }))
    else response.end(JSON.stringify({ run_id: "run-1", status: state }))
  })
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== "string")
    const client = new AgentServerClient(`http://127.0.0.1:${address.port}`)
    assert.equal(await client.getAuditResult("run-1", ["security"]), null)
    assert.deepEqual(paths, ["/api/audits/run-1"])
    state = "partial"
    const result = await client.getAuditResult("run-1", ["security"])
    assert.equal(result?.["status"], "partial")
    assert.equal(result?.["docx_base64"], Buffer.from("PK-document").toString("base64"))
    assert.deepEqual(result?.["attributes"], ["security"])
    state = "missing"
    await assert.rejects(() => client.getAuditResult("run-1", []), AuditRunUnavailableError)
  } finally {
    server.closeAllConnections()
    await new Promise<void>((resolve) => server.close(() => resolve()))
  }
})

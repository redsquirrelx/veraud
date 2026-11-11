import assert from "node:assert/strict"
import { test } from "node:test"
import Fastify from "fastify"
import { invocationEvents, invocationReceiptSchema, type InvocationReceipt } from "./invocationReceipt.js"

test("invocation HTTP validation and serialization retain partial-usage metadata", async () => {
  const app = Fastify()
  app.post<{ Body: InvocationReceipt }>("/receipt", {
    schema: { body: invocationReceiptSchema, response: { 200: invocationReceiptSchema } },
  }, async (request) => invocationEvents([request.body])[0])
  try {
    const payload: InvocationReceipt = {
      invocation_id: "responsibility", parent_invocation_id: "modularity", agent_id: "responsibility", run_id: "audit",
      status: "running", started_at: "2026-11-10T23:00:00Z", finished_at: null,
      input_tokens: 150, output_tokens: 30, unknown_usage_attempts: 1, error: null,
    }
    const response = await app.inject({ method: "POST", url: "/receipt", payload })
    assert.equal(response.statusCode, 200, response.body)
    assert.equal(response.json().unknown_usage_attempts, 1)
    assert.equal(response.json().input_tokens, 150)
    const invalid = await app.inject({ method: "POST", url: "/receipt", payload: { ...payload, unknown_usage_attempts: -1 } })
    assert.equal(invalid.statusCode, 400)
  } finally {
    await app.close()
  }
})

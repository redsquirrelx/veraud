import assert from "node:assert/strict"
import type { FastifyInstance, FastifyRequest } from "fastify"

/** Compare controller payloads with serialized HTTP bodies, independent of schema definitions. */
export function auditResponseSerialization(app: FastifyInstance): void {
  const expected = new WeakMap<FastifyRequest, unknown>()
  const failures: string[] = []

  app.addHook("preSerialization", async (request, _reply, payload) => {
    if (request.url.startsWith("/api/") || request.url === "/status") {
      // JSON.stringify is the pre-schema HTTP behavior, including Date -> ISO.
      expected.set(request, JSON.parse(JSON.stringify(payload)))
    }
    return payload
  })

  app.addHook("onSend", async (request, reply, payload) => {
    if (!request.url.startsWith("/api/") && request.url !== "/status") return payload
    try {
      if (reply.statusCode === 204) {
        assert.ok(payload === null || payload === undefined || payload === "", "204 must have no body")
      } else if (expected.has(request)) {
        assert.equal(typeof payload, "string", "Expected a serialized JSON response")
        assert.deepEqual(JSON.parse(String(payload)), expected.get(request))
      }
    } catch (error) {
      failures.push(`${request.method} ${request.url} (${reply.statusCode}): ${error instanceof Error ? error.message : String(error)}`)
    }
    return payload
  })

  app.addHook("onClose", async () => {
    assert.deepEqual(failures, [], "Response serialization changed controller payloads")
  })
}

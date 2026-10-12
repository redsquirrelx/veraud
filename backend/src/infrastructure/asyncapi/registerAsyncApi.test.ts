import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import { describe, it } from "node:test"
import { Script, runInNewContext } from "node:vm"
import Fastify from "fastify"
import { Parser } from "@asyncapi/parser"
import { registerOpenApi } from "../openapi/registerOpenApi.js"
import { registerAsyncApi } from "./registerAsyncApi.js"

describe("AsyncAPI portal", () => {
  it("serves the generated specification and local assets alongside Swagger", async () => {
    const app = Fastify({ logger: false })
    try {
      await registerOpenApi(app)
      await registerAsyncApi(app)
      for (const url of ["/docs/ws", "/docs/ws/"]) {
        const response = await app.inject({ url })
        assert.equal(response.statusCode, 200)
        assert.match(String(response.headers["content-type"]), /text\/html/)
        assert.match(response.body, /Veraud Backend WebSocket API/)
        assert.match(response.body, /href="\/docs"/)
        assert.match(response.body, /href="\/docs\/ws\/spec"/)
        assert.doesNotMatch(response.body, /https?:\/\//)
      }
      const specification = await app.inject({ url: "/docs/ws/spec" })
      assert.equal(specification.statusCode, 200)
      assert.match(String(specification.headers["content-type"]), /application\/yaml/)
      assert.equal(specification.body, await readFile(new URL("./asyncapi.yaml", import.meta.url), "utf8"))
      const { document, diagnostics } = await new Parser().parse(specification.body)
      assert.ok(document)
      assert.deepEqual(diagnostics, [])
      assert.equal(document.messages().length, 3)

      for (const name of ["asyncapi.js", "asyncapi.css", "portal.js", "portal.css"]) {
        const asset = await app.inject({ url: `/docs/ws/assets/${name}` })
        assert.equal(asset.statusCode, 200)
        assert.match(String(asset.headers["content-type"]), name.endsWith(".js") ? /javascript/ : /text\/css/)
        assert.ok(asset.body.length > 0)
        if (name.endsWith(".js")) new Script(asset.body)
      }
      assert.equal((await app.inject({ url: "/docs/ws/assets/index.js.LICENSE.txt" })).statusCode, 200)
      for (const url of ["/docs/", "/docs/json", "/docs/static/swagger-ui.css"]) {
        assert.equal((await app.inject({ url })).statusCode, 200)
      }
      const openapi = (await app.inject({ url: "/docs/json" })).json()
      assert.deepEqual(openapi.paths, {})
      assert.match(openapi.info.description, /\[WebSocket AsyncAPI documentation\]\(\/docs\/ws\)/)
      assert.equal((await app.inject({ url: "/docs/ws/assets/missing.js" })).statusCode, 404)
    } finally {
      await app.close()
    }
  })

  it("loads the same-origin spec, shows ws/wss addresses and handles HTTP errors", async () => {
    const bootstrap = await readFile(new URL("./portal/portal.js", import.meta.url), "utf8")
    for (const protocol of ["http:", "https:"]) {
      const elements = {
        "ws-address": { textContent: "" },
        "portal-status": { textContent: "", hidden: false },
        asyncapi: { querySelectorAll: () => [] },
      }
      let rendered: unknown
      const context = {
        URL,
        MutationObserver: class { observe() {} },
        window: { location: { href: `${protocol}//example.test:8123/docs/ws`, protocol } },
        document: { getElementById: (id: keyof typeof elements) => elements[id] },
        fetch: async (url: string) => {
          assert.equal(url, "/docs/ws/spec")
          return { ok: true, text: async () => "asyncapi: 3.1.0" }
        },
        AsyncApiStandalone: { render: (props: { schema: string }, target: unknown) => {
          rendered = props.schema
          assert.equal(target, elements.asyncapi)
        } },
      }
      await runInNewContext(bootstrap.replace("void showDocumentation()", "showDocumentation()"), context)
      assert.equal(rendered, "asyncapi: 3.1.0")
      assert.equal(elements["ws-address"].textContent, `${protocol === "https:" ? "wss:" : "ws:"}//example.test:8123/ws`)
      assert.equal(elements["portal-status"].hidden, true)
      context.fetch = async () => ({ ok: false, status: 503, text: async () => "" })
      elements["portal-status"].hidden = false
      await runInNewContext(bootstrap.replace("void showDocumentation()", "showDocumentation()"), { ...context })
      assert.match(elements["portal-status"].textContent, /Specification request failed \(503\)/)
      assert.equal(elements["portal-status"].hidden, false)
    }
  })
})

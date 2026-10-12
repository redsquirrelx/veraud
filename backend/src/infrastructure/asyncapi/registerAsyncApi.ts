import type { FastifyInstance, FastifyReply } from "fastify"
import { loadPortalResources } from "./loadPortalResources.js"

function sendResource(reply: FastifyReply, contentType: string, body: string | Buffer) {
  return reply.type(contentType).header("Cache-Control", "no-cache").send(body)
}

export async function registerAsyncApi(app: FastifyInstance): Promise<void> {
  const { html, specification, assets } = await loadPortalResources()
  const options = { schema: { hide: true } }
  const servePortal = async (_request: unknown, reply: FastifyReply) =>
    sendResource(reply, "text/html; charset=utf-8", html)

  app.get("/docs/ws", options, servePortal)
  app.get("/docs/ws/", options, servePortal)
  app.get("/docs/ws/spec", options, async (_request, reply) =>
    sendResource(reply, "application/yaml; charset=utf-8", specification))
  for (const asset of assets) {
    app.get(`/docs/ws/assets/${asset.name}`, options, async (_request, reply) =>
      sendResource(reply, asset.contentType, asset.body))
  }
}

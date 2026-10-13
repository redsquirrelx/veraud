import type { FastifyInstance } from "fastify"
import type { WebSocket } from "ws"
import { logger } from "../../config/logger.js"

import type { GatewayEvent } from "./eventCatalog.js"
export type { TaskEvent, AgentExecutionEvent, GatewayEvent, GatewayWireEvent } from "./eventCatalog.js"

export class RealtimeGateway {
  private log = logger.withTag("realtime-gateway")
  private sockets = new Set<WebSocket>()

  register(app: FastifyInstance): void {
    app.get("/ws", { websocket: true, schema: { hide: true } }, (socket) => {
      this.sockets.add(socket)
      this.log.info("Client connected")

      socket.on("close", () => {
        this.sockets.delete(socket)
        this.log.info("Client disconnected")
      })
    })
  }

  broadcast(event: GatewayEvent): void {
    const message = JSON.stringify(event)

    for (const socket of this.sockets) {
      try {
        socket.send(message)
      } catch (error) {
        this.log.error(`Could not send event: ${error}`)
      }
    }
  }
}

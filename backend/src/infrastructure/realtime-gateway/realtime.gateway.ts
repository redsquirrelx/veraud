import type { FastifyInstance } from "fastify"
import type { WebSocket } from "ws"
import { logger } from "../../config/logger.js"

export interface TaskEvent {
  type: "task.updated"
  task: {
    id: number
    projectId: number
    description: string | null
    status: string
    kind: string
    exitCode: number | null
  }
}

export interface AgentExecutionEvent {
  type: "agent-execution.opened" | "agent-execution.updated"
  execution: {
    id: number
    evaluationId: number
    agentType: string
    status: string
    result: string | null
    error: string | null
    inputTokens: number | null
    outputTokens: number | null
    createdAt: Date
    startedAt: Date | null
    finishedAt: Date | null
  }
}

export type GatewayEvent = TaskEvent | AgentExecutionEvent

export class RealtimeGateway {
  private log = logger.withTag("realtime-gateway")
  private sockets = new Set<WebSocket>()

  register(app: FastifyInstance): void {
    app.get("/ws", { websocket: true }, (socket) => {
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

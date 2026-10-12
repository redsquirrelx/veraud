import type { FastifyInstance } from "fastify"
import type { TaskService } from "./task.service.js"

export function registerTaskRoutes(app: FastifyInstance, service: TaskService): void {
  app.get("/api/tasks/active", { schema: {
    tags: ["Tasks"], summary: "List active Git tasks",
    description: "Returns Queued/Running tasks ordered by ID. Includes the readable command (null for legacy tasks). An empty list is valid; finished tasks are followed through WebSocket events.",
    response: { 200: { type: "array", items: { $ref: "Task#" } } },
  } }, async () => {
    const tasks = await service.listActive()

    return tasks.map((task) => ({
      id: task.id,
      projectId: task.projectId,
      repositoryOwner: task.repositoryOwner,
      repositoryName: task.repositoryName,
      description: task.description,
      command: task.command ?? null,
      status: task.status,
      kind: task.kind,
      exitCode: task.exitCode,
    }))
  })
}

import type { FastifyInstance } from "fastify"
import type { TaskService } from "./task.service.js"

export function registerTaskRoutes(app: FastifyInstance, service: TaskService): void {
  app.get("/api/tasks/active", async () => {
    const tasks = await service.listActive()

    return tasks.map((task) => ({
      id: task.id,
      projectId: task.projectId,
      repositoryOwner: task.repositoryOwner,
      repositoryName: task.repositoryName,
      description: task.description,
      status: task.status,
      exitCode: task.exitCode,
    }))
  })
}

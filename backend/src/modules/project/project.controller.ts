import type { FastifyInstance } from "fastify"
import { RepoNotAccessibleError } from "../../infrastructure/github-client/github.client.js"
import { DuplicateProjectError, InvalidUrlError, ProjectService } from "./project.service.js"

export function registerProjectRoutes(app: FastifyInstance, service: ProjectService): void {
  app.post("/api/projects", {
    schema: {
      body: {
        type: "object",
        required: ["repositoryUrl"],
        properties: {
          repositoryUrl: { type: "string" },
        },
      },
    },
  }, async (request, reply) => {
    const body = request.body as { repositoryUrl: string }

    try {
      const project = await service.registerProject(body.repositoryUrl)
      return reply.code(201).send({
        id: project.id,
        repositoryOwner: project.repositoryOwner,
        repositoryName: project.repositoryName,
        status: project.status,
      })
    } catch (error) {
      if (error instanceof InvalidUrlError) {
        return reply.code(400).send({ message: error.message })
      }
      if (error instanceof DuplicateProjectError) {
        return reply.code(409).send({ message: error.message })
      }
      if (error instanceof RepoNotAccessibleError) {
        return reply.code(422).send({ message: error.message })
      }
      throw error
    }
  })
}

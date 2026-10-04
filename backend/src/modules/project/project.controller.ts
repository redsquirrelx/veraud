import type { FastifyInstance } from "fastify"
import { RepoNotAccessibleError } from "../../infrastructure/github-client/github.client.js"
import { DuplicateProjectError, InvalidUrlError, ProjectNotFoundError, ProjectService, SyncFailedError } from "./project.service.js"

export function registerProjectRoutes(app: FastifyInstance, service: ProjectService): void {
  app.get("/api/projects", async () => {
    const projects = await service.listProjects()
    return projects.map((project) => ({
      id: project.id,
      repositoryOwner: project.repositoryOwner,
      repositoryName: project.repositoryName,
      status: project.status,
      registeredAt: project.registeredAt,
      lastSyncedAt: project.lastSyncedAt,
      branch: project.branch,
      commitHash: project.commitHash,
    }))
  })

  app.post("/api/projects/:id/sync", {
    schema: {
      params: {
        type: "object",
        required: ["id"],
        properties: {
          id: { type: "string", pattern: "^[0-9]+$" },
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }

    try {
      const project = await service.syncProject(Number(params.id))
      return reply.code(200).send({
        id: project.id,
        repositoryOwner: project.repositoryOwner,
        repositoryName: project.repositoryName,
        status: project.status,
        registeredAt: project.registeredAt,
        lastSyncedAt: project.lastSyncedAt,
        branch: project.branch,
        commitHash: project.commitHash,
      })
    } catch (error) {
      if (error instanceof ProjectNotFoundError) {
        return reply.code(404).send({ message: error.message })
      }
      if (error instanceof SyncFailedError) {
        return reply.code(422).send({ message: error.message })
      }
      throw error
    }
  })

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

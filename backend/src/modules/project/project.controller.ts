import type { FastifyInstance } from "fastify"
import { RepoNotAccessibleError } from "../../infrastructure/github-client/github.client.js"
import { DuplicateProjectError, GitOperationError, InvalidGitRequestError, InvalidUrlError, ProjectNotFoundError, ProjectService, SyncFailedError, WorkspaceMissingError } from "./project.service.js"

const idParams = {
  type: "object",
  required: ["id"],
  properties: {
    id: { type: "string", pattern: "^[0-9]+$" },
  },
} as const

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

  app.post("/api/projects/:id/git/branches", {
    schema: { params: idParams },
  }, async (request, reply) => {
    const params = request.params as { id: string }

    try {
      const result = await service.listBranches(Number(params.id))
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/git/rev-parse", {
    schema: {
      params: idParams,
      body: {
        type: "object",
        required: ["branch"],
        properties: {
          branch: { type: "string" },
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { branch: string }

    try {
      const result = await service.resolveBranchHash(Number(params.id), body.branch)
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/git/log", {
    schema: {
      params: idParams,
      body: {
        type: "object",
        required: ["branch"],
        properties: {
          branch: { type: "string" },
          limit: { type: "integer" },
          offset: { type: "integer" },
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { branch: string, limit?: number, offset?: number }

    try {
      const result = await service.listCommits(Number(params.id), body.branch, body.limit, body.offset)
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/git/checkout", {
    schema: {
      params: idParams,
      body: {
        type: "object",
        required: ["commitHash"],
        properties: {
          commitHash: { type: "string" },
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { commitHash: string }

    try {
      const result = await service.checkoutCommit(Number(params.id), body.commitHash)
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })
}

function gitErrorCode(error: unknown): number {
  if (error instanceof ProjectNotFoundError) {
    return 404
  }

  if (error instanceof InvalidGitRequestError) {
    return 400
  }

  return 422
}

function gitErrorMessage(error: unknown): string {
  if (error instanceof ProjectNotFoundError || error instanceof InvalidGitRequestError || error instanceof WorkspaceMissingError || error instanceof GitOperationError) {
    return error.message
  }

  throw error
}

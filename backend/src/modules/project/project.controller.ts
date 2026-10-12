import type { FastifyInstance } from "fastify"
import { branchInput, commitHashInput, errorResponses, objectResponse } from "../../infrastructure/openapi/routeSchemas.js"
import { RepoNotAccessibleError } from "../../infrastructure/github-client/github.client.js"
import { UnknownExecutionTargetError, type StoredAgentExecution } from "../agent-execution/agent-execution.repository.js"
import { DuplicateProjectError, AnalysisAlreadyRunningError, GitOperationError, InvalidGitRequestError, InvalidUrlError, ProjectFileError, ProjectNotFoundError, ProjectService, SyncFailedError, WorkspaceMissingError } from "./project.service.js"

const idParams = {
  type: "object",
  required: ["id"],
  properties: {
    id: { type: "string", pattern: "^[0-9]+$", description: "Project ID.", examples: ["1"] },
  },
} as const

export function registerProjectRoutes(app: FastifyInstance, service: ProjectService): void {
  app.get("/api/projects", { schema: {
    tags: ["Projects"], summary: "List projects",
    description: "Returns all registered projects ordered by ID, with their selected version. Filtering and paging are client-side.",
    response: { 200: { type: "array", items: { $ref: "ProjectSummary#" } } },
  } }, async () => {
    const projects = await service.listProjects()
    return projects.map((project) => ({
      id: project.id,
      repositoryOwner: project.repositoryOwner,
      repositoryName: project.repositoryName,
      cloneProtocol: project.cloneProtocol,
      status: project.status,
      registeredAt: project.registeredAt,
      lastSyncedAt: project.lastSyncedAt,
      branch: project.branch,
      commitHash: project.commitHash,
    }))
  })

  app.post("/api/projects/:id/sync", {
    schema: {
      tags: ["Projects"], summary: "Synchronize a project",
      description: "Waits for clone if the workspace is empty, pull for an attached checkout, or fetch for detached HEAD. Recloning preserves HTTPS/SSH and shallowClone; fetch does not move HEAD or automatically unshallow the repository.",
      response: { 200: { $ref: "ProjectSummary#" }, ...errorResponses([400, 404, 422], "MessageError", false) },
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
        cloneProtocol: project.cloneProtocol,
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
      tags: ["Projects"], summary: "Register and clone a repository",
      description: "Waits for cloning to succeed. HTTPS checks GitHub metadata; SSH uses the backend user's SSH configuration without a public metadata lookup. Failure rolls back the new project and task. Returns the initial QUEUED snapshot, although the stored status may already be READY.",
      response: { 201: { $ref: "RegisteredProject#" }, ...errorResponses([400, 409, 422]) },
      body: {
        type: "object",
        required: ["repositoryUrl"],
        properties: {
          repositoryUrl: { type: "string", description: "GitHub HTTPS, git@github.com:owner/repo.git, or ssh://git@github.com/owner/repo.git URL.", examples: ["https://github.com/octocat/Hello-World", "git@github.com:owner/repo.git"] },
          shallowClone: { type: "boolean", description: "true adds --depth 1 (latest commit of the default branch); omitted means false (full clone).", examples: [true] },
        },
      },
    },
  }, async (request, reply) => {
    const body = request.body as { repositoryUrl: string; shallowClone?: boolean }

    try {
      const project = await service.registerProject(body.repositoryUrl, body.shallowClone ?? false)
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
    schema: { params: idParams, tags: ["Project Git"], summary: "List local and remote branches",
      description: "Waits for a read-only Git task. Deduplicates branch names and reports attached or detached HEAD. Only locally available refs are returned, including for shallow clones. No body is required.",
      response: { 200: objectResponse({ branches: { type: "array", items: { type: "string" } }, currentBranch: { type: ["string", "null"] }, detachedHash: { type: ["string", "null"] }, taskId: { type: "integer" } }), ...errorResponses([400, 404, 422]) } },
  }, async (request, reply) => {
    const params = request.params as { id: string }

    try {
      const result = await service.listBranches(Number(params.id))
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/git/tree", {
    schema: { params: idParams, tags: ["Project Git"], summary: "List tracked files at HEAD",
      description: "Waits for git ls-tree; returns slash-separated repository-relative file paths for the current checkout. No body is required.",
      response: { 200: objectResponse({ files: { type: "array", items: { type: "string" } }, taskId: { type: "integer" } }), ...errorResponses([400, 404, 422]) } },
  }, async (request, reply) => {
    const params = request.params as { id: string }

    try {
      const result = await service.listTree(Number(params.id))
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/file", {
    schema: {
      tags: ["Projects"], summary: "Read a checkout text file",
      description: "Reads UTF-8 content without creating a task. Rejects missing files, directories, files larger than 512 KiB and content with null bytes.",
      response: { 200: objectResponse({ path: { type: "string" }, content: { type: "string" }, size: { type: "integer", description: "File size in bytes." } }), ...errorResponses([400, 404, 422]) },
      params: idParams,
      body: {
        type: "object",
        required: ["path"],
        properties: {
          path: { type: "string", description: "Relative path, trimmed, up to 1024 characters; backslashes normalized. Empty segments, . and .., null bytes and .git paths are rejected.", examples: ["src/index.ts"] },
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { path: string }

    try {
      const result = await service.readFile(Number(params.id), body.path)
      return reply.code(200).send(result)
    } catch (error) {
      if (error instanceof ProjectFileError) {
        return reply.code(422).send({ message: error.message })
      }
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/git/rev-parse", {
    schema: {
      tags: ["Project Git"], summary: "Resolve a branch commit hash",
      description: "Waits for a read-only Git task and returns the full 40-character lowercase commit hash.",
      response: { 200: objectResponse({ branch: { type: "string" }, commitHash: { type: "string" }, taskId: { type: "integer" } }), ...errorResponses([400, 404, 422]) },
      params: idParams,
      body: {
        type: "object",
        required: ["branch"],
        properties: {
          branch: branchInput,
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
      tags: ["Project Git"], summary: "List branch commits",
      description: "Waits for a read-only Git task. History reflects commits available in the local checkout; shallow clones initially contain only the branch tip.",
      response: { 200: objectResponse({ branch: { type: "string" }, commits: { type: "array", items: objectResponse({ commitHash: { type: "string" }, subject: { type: "string" } }) }, limit: { type: "integer" }, offset: { type: "integer" }, taskId: { type: "integer" } }), ...errorResponses([400, 404, 422]) },
      params: idParams,
      body: {
        type: "object",
        required: ["branch"],
        properties: {
          branch: branchInput,
          limit: { type: "integer", description: "Service default: 30. Valid range: 1ΓÇô100.", examples: [30] },
          offset: { type: "integer", description: "Service default: 0. Must be non-negative.", examples: [0] },
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
      tags: ["Project Git"], summary: "Check out a commit with detached HEAD",
      description: "Waits for git checkout --force --detach. Discards checkout changes; the task is retained, including on failure.",
      response: { 200: objectResponse({ commitHash: { type: "string" }, taskId: { type: "integer" } }), ...errorResponses([400, 404, 422]) },
      params: idParams,
      body: {
        type: "object",
        required: ["commitHash"],
        properties: {
          commitHash: commitHashInput,
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

  app.post("/api/projects/:id/git/checkout-branch", {
    schema: {
      tags: ["Project Git"], summary: "Check out a branch",
      description: "Waits for git checkout --force, attaching HEAD. Remote-only branches can materialize as local tracking branches.",
      response: { 200: objectResponse({ branch: { type: "string" }, taskId: { type: "integer" } }), ...errorResponses([400, 404, 422]) },
      params: idParams,
      body: {
        type: "object",
        required: ["branch"],
        properties: {
          branch: branchInput,
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { branch: string }

    try {
      const result = await service.checkoutBranch(Number(params.id), body.branch)
      return reply.code(200).send(result)
    } catch (error) {
      return reply.code(gitErrorCode(error)).send({ message: gitErrorMessage(error) })
    }
  })

  app.post("/api/projects/:id/analyze", {
    schema: {
      tags: ["Projects"], summary: "Start analysis of a project version",
      description: "Saves or reuses and selects the version, creates an evaluation and starts the analyzer in the background. Does not check out the commit. Rejects an already-open execution for the same commit; completion arrives later through callbacks/WebSocket.",
      response: { 201: objectResponse({ versionId: { type: "integer" }, evaluationId: { type: "integer" }, execution: { $ref: "AgentExecution#" } }), ...errorResponses([400, 404, 422]) },
      params: idParams,
      body: {
        type: "object",
        required: ["branch", "commitHash"],
        properties: {
          branch: branchInput,
          commitHash: commitHashInput,
        },
      },
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    const body = request.body as { branch: string; commitHash: string }

    try {
      const result = await service.analyzeProject(Number(params.id), body.branch, body.commitHash)
      return reply.code(201).send({
        versionId: result.versionId,
        evaluationId: result.evaluationId,
        execution: toExecution(result.execution),
      })
    } catch (error) {
      if (error instanceof ProjectNotFoundError) {
        return reply.code(404).send({ message: error.message })
      }
      if (error instanceof InvalidGitRequestError) {
        return reply.code(400).send({ message: error.message })
      }
      if (error instanceof WorkspaceMissingError || error instanceof UnknownExecutionTargetError || error instanceof AnalysisAlreadyRunningError) {
        return reply.code(422).send({ message: error.message })
      }
      throw error
    }
  })

  app.get("/api/projects/:id/versions", {
    schema: { params: idParams, tags: ["Projects"], summary: "List analyzed project versions",
      description: "Returns versions newest first, with their latest evaluation/execution and derived status. An empty list is valid.",
      response: { 200: { type: "array", items: { $ref: "VersionAnalysis#" } }, ...errorResponses([400, 404], "MessageError", false) } },
  }, async (request, reply) => {
    const params = request.params as { id: string }

    try {
      const versions = await service.listVersions(Number(params.id))
      return reply.code(200).send(versions.map((version) => ({
        id: version.id,
        branch: version.branch,
        commitHash: version.commitHash,
        analysisStatus: version.analysisStatus,
        analyzedAt: version.analyzedAt,
        evaluationId: version.evaluationId,
        execution: version.execution === null ? null : toExecution(version.execution),
        derivedStatus: version.derivedStatus,
      })))
    } catch (error) {
      if (error instanceof ProjectNotFoundError) {
        return reply.code(404).send({ message: error.message })
      }
      throw error
    }
  })
}

function gitErrorCode(error: unknown): 400 | 404 | 422 {
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

function toExecution(execution: StoredAgentExecution) {
  return {
    id: execution.id,
    evaluationId: execution.evaluationId,
    agentType: execution.agentType,
    status: execution.status,
    result: execution.result,
    error: execution.error,
    inputTokens: execution.inputTokens,
    outputTokens: execution.outputTokens,
    createdAt: execution.createdAt,
    startedAt: execution.startedAt,
    finishedAt: execution.finishedAt,
  }
}

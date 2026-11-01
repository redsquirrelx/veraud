import { Readable } from "node:stream"
import type { FastifyInstance } from "fastify"
import type { TaskQueue } from "../../infrastructure/task-runner/task.types.js"
import { GRAPH_PHASES, GRAPH_ERROR_CODES, GraphRequestError, type GraphErrorCode, type GraphPhase, type ProjectGraphService } from "./project-graph.service.js"

const projectParams = { type: "object", required: ["id"], properties: { id: { type: "integer", minimum: 1 } } }
const taskParams = { type: "object", required: ["id", "taskId"], properties: { id: { type: "integer", minimum: 1 }, taskId: { type: "integer", minimum: 1 } } }

export function registerProjectGraphRoutes(app: FastifyInstance, service: ProjectGraphService, queue: TaskQueue) {
  app.post<{ Params: { id: number }, Body: { branch: string, commitHash: string, regenerate?: boolean } }>("/api/projects/:id/graph", { schema: {
    tags: ["Projects"], summary: "Start independent Graphify extraction", params: projectParams,
    body: { type: "object", additionalProperties: false, required: ["branch", "commitHash"], properties: {
      branch: { type: "string", minLength: 1, maxLength: 255 }, commitHash: { type: "string", pattern: "^[a-f0-9]{40}$" },
      regenerate: { type: "boolean" },
    } },
  } }, async (request, reply) => {
    try { return reply.code(202).send(await service.start(request.params.id, request.body.branch, request.body.commitHash, queue, request.body.regenerate)) }
    catch (error) { if (error instanceof GraphRequestError) return reply.code(error.statusCode).send({ message: error.message }); throw error }
  })
  app.get<{ Params: { id: number }, Querystring: { commitHash?: string } }>("/api/projects/:id/graph", { schema: {
    tags: ["Projects"], summary: "Get latest graph extraction state", params: projectParams,
    querystring: { type: "object", properties: { commitHash: { type: "string", pattern: "^[a-f0-9]{40}$" } } },
  } }, (request) => service.get(request.params.id, undefined, request.query.commitHash))
  app.get<{ Params: { id: number, taskId: number } }>("/api/projects/:id/graph/:taskId/artifact", { schema: { tags: ["Projects"], summary: "Download completed graph", params: taskParams } }, async (request, reply) => {
    try {
      const response = await service.artifact(request.params.id, request.params.taskId)
      return reply.type("application/json").header("Content-Disposition", 'attachment; filename="graph.json"').send(Readable.fromWeb(response.body! as import("node:stream/web").ReadableStream))
    } catch (error) { if (error instanceof GraphRequestError) return reply.code(error.statusCode).send({ message: error.message }); throw error }
  })
  app.post<{ Params: { taskId: number }, Body: { phase: GraphPhase, errorCode?: GraphErrorCode } }>("/api/tasks/:taskId/graph-callback", { logLevel: "silent", schema: {
    hide: true, params: { type: "object", required: ["taskId"], properties: { taskId: { type: "integer", minimum: 1 } } },
    body: { type: "object", additionalProperties: false, required: ["phase"], properties: { phase: { type: "string", enum: [...GRAPH_PHASES] }, errorCode: { type: "string", enum: [...GRAPH_ERROR_CODES] } } },
  } }, async (request, reply) => {
    try { await service.callback(request.params.taskId, String(request.headers["x-graph-token"] ?? ""), request.body.phase, request.body.errorCode); return { acknowledged: true } }
    catch (error) { if (error instanceof GraphRequestError) return reply.code(error.statusCode).send({ message: error.message }); throw error }
  })
}

import type { FastifyInstance } from "fastify"
import { errorResponses, objectResponse } from "../../infrastructure/openapi/routeSchemas.js"
import { ProjectDeletionBusyError, ProjectDeletionNotFoundError, ProjectDeletionService } from "./project-deletion.service.js"

const idParams = {
  type: "object",
  required: ["id"],
  properties: {
    id: { type: "string", pattern: "^[0-9]+$", description: "Project ID.", examples: ["1"] },
  },
} as const

const deletionCountsSchema = objectResponse({
  versions: { type: "integer" },
  evaluations: { type: "integer" },
  executions: { type: "integer" },
  events: { type: "integer" },
  architectureArtifacts: { type: "integer" },
  tasks: { type: "integer" },
  graphExtractions: { type: "integer" },
})

const deletionDiskSchema = objectResponse({
  artifactsRemoved: { type: "array", items: { type: "string" } },
  artifactsSkipped: { type: "integer", description: "Artifact directories found but rejected as unsafe to remove." },
  artifactFailures: { type: "array", items: { type: "string" } },
  cloneRemoved: { type: "boolean" },
  cloneFailure: { type: ["string", "null"] },
})

/** DELETE /api/projects/:id — irreversible: cancels open audit executions and
 *  waits for them to terminate, wipes the project's database rows in one
 *  transaction and best-effort removes the checkout and run artifacts. */
export function registerProjectDeletionRoutes(app: FastifyInstance, service: ProjectDeletionService): void {
  app.delete("/api/projects/:id", {
    schema: {
      tags: ["Projects"],
      summary: "Delete a project permanently",
      description: "Irreversible. Requests cancellation of this project's open (Waiting/Running) audit executions and waits for them to terminate, bounded by a timeout; if they do not finish in time, nothing is deleted and 202 is returned with the pending execution IDs — retry the call to finish the deletion. Queued/Running git tasks cannot be cancelled and yield 422. On success removes, in one transaction, architecture-context artifacts, execution event streams/events, agent executions, evaluations, tasks (and their graph extractions), project versions and the project itself, then best-effort deletes the checkout and the .veraud-artifacts/<run_id> directories whose run_id is present in the executions' result JSON. Disk failures are reported in the response and never roll back the database. The database file itself is not shrunk.",
      response: {
        200: objectResponse({
          status: { type: "string", enum: ["deleted"] },
          counts: deletionCountsSchema,
          disk: deletionDiskSchema,
        }),
        202: objectResponse({
          status: { type: "string", enum: ["cancelling"] },
          message: { type: "string" },
          pendingExecutionIds: { type: "array", items: { type: "integer" } },
        }),
        ...errorResponses([404, 422]),
      },
      params: idParams,
    },
  }, async (request, reply) => {
    const params = request.params as { id: string }
    try {
      const outcome = await service.deleteProject(Number(params.id))
      if (outcome.status === "cancelling") {
        return reply.code(202).send({
          status: "cancelling",
          message: "Open executions were asked to cancel; retry in a few seconds",
          pendingExecutionIds: outcome.pendingExecutionIds,
        })
      }
      return reply.code(200).send({ status: "deleted", counts: outcome.counts, disk: outcome.disk })
    } catch (error) {
      if (error instanceof ProjectDeletionNotFoundError) {
        return reply.code(404).send({ message: error.message })
      }
      if (error instanceof ProjectDeletionBusyError) {
        return reply.code(422).send({ message: error.message })
      }
      throw error
    }
  })
}

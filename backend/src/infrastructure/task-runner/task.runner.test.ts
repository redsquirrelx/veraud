import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import type { FastifyBaseLogger } from "fastify"
import { logger } from "../../config/logger.js"
import type { TaskEvent } from "../realtime-gateway/realtime.gateway.js"
import type { StoredTask, TaskStore } from "../../modules/task/task.repository.js"
import { TaskRunner } from "./task.runner.js"

const quiet = { child: () => ({ info() {}, warn() {}, error() {}, debug() {} }) }
logger.configure(quiet as unknown as FastifyBaseLogger)

const stored: StoredTask = {
  id: 1,
  projectId: 2,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  description: "cloning acme/Demo",
  status: "Queued",
  exitCode: null,
}

describe("TaskRunner.enqueueClone", () => {
  it("announces the queued task before running it", async () => {
    const events: TaskEvent[] = []
    const store: TaskStore = {
      create: async () => stored,
      update: async (_id, data) => ({ ...stored, ...data }),
      delete: async () => {},
      findById: async () => stored,
      findActive: async () => [],
    }
    const runner = new TaskRunner(store, { broadcast: (event) => { events.push(event) } }, mkdtempSync(join(tmpdir(), "veraud-runner-")))

    const result = await runner.enqueueClone(1, 2, "not-a-repo", "folder")

    assert.equal(result.status, "Failed")
    assert.deepEqual(events.map((event) => event.task.status), ["Queued", "Running", "Failed"])
  })
})

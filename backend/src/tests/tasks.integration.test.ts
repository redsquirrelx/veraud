import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { auditResponseSerialization } from "./helpers/responseSerializationAudit.js"

/** Integration for the task listing wiring: Fastify route → TaskService → TaskRepository (join) →
 *  SQLite. Task execution itself (git executor over HTTP sync) is covered by project-git.integration;
 *  this covers the /api/tasks/active contract: filter, order and field mapping. */
function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-test-"))
  const url = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: url }, stdio: "ignore",
  })
  return url
}

it("lists only Queued/Running tasks in id order with mapped project fields and no internals", async () => {
  const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-ws-"))
  const { app, db } = await buildApp({ databaseUrl: freshDatabase(), workspaceDir, silent: true })
  auditResponseSerialization(app)
  try {
    const project = await db.project.create({ data: { githubRepositoryId: 779n, repositoryOwner: "acme", repositoryName: "tasks-demo", status: "READY" } })
    await db.task.create({ data: { projectId: project.id, description: "clone latest", status: "Queued", kind: "git", command: "git clone" } })
    await db.task.create({ data: { projectId: project.id, description: "pull", status: "Running", kind: "git", command: "git pull" } })
    await db.task.create({ data: { projectId: project.id, description: "done", status: "Succeded", kind: "git", command: "git fetch", exitCode: 0 } })
    await db.task.create({ data: { projectId: project.id, description: "boom", status: "Failed", kind: "git", command: "git clone", exitCode: 128 } })

    const response = await app.inject({ url: "/api/tasks/active" })
    assert.equal(response.statusCode, 200)
    const body = response.json() as Array<Record<string, unknown>>
    assert.deepEqual(body.map((task) => task.status), ["Queued", "Running"])
    assert.deepEqual(body.map((task) => task.id), [1, 2])
    assert.deepEqual(Object.keys(body[0]!).sort(),
      ["command", "description", "exitCode", "id", "kind", "projectId", "repositoryName", "repositoryOwner", "status"])
    assert.equal(body[0]!["repositoryOwner"], "acme")
    assert.equal(body[0]!["repositoryName"], "tasks-demo")
    assert.equal(body[0]!["command"], "git clone")
    assert.equal(body[1]!["command"], "git pull")
    assert.equal(body[0]!["exitCode"], null)
    assert.equal(body[1]!["exitCode"], null)

    // An empty workspace shows an empty list, not an error.
    await db.task.updateMany({ data: { status: "Succeded" } })
    const empty = await app.inject({ url: "/api/tasks/active" })
    assert.equal(empty.statusCode, 200)
    assert.deepEqual(empty.json(), [])
  } finally {
    await app.close()
    await db.$disconnect()
  }
})

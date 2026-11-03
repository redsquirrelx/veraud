import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { buildApp } from "../app.js"
import { QualityAuditRepository } from "../modules/quality-audit/quality-audit.repository.js"

it("paginates lightweight audit summaries without materializing stored artifacts", async () => {
  const dir = mkdtempSync(join(tmpdir(), "veraud-audit-list-"))
  const databaseUrl = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const { app, db } = await buildApp({ databaseUrl, workspaceDir: join(dir, "workspace"), silent: true })
  try {
    const project = await db.project.create({ data: { githubRepositoryId: 987654n, repositoryOwner: "acme", repositoryName: "list", status: "READY" } })
    const version = await db.projectVersion.create({ data: { projectId: project.id, branch: "changed", commitHash: "b".repeat(40), analysisStatus: "Completed" } })
    const evaluation = await db.evaluation.create({ data: { projectVersionId: version.id, type: "QualityAudit" } })
    const agent = await db.agentSettings.create({ data: { agentType: "security" } })
    const large = "artifact-not-for-history".repeat(100000)
    const ids: number[] = []
    for (let index = 0; index < 7; index++) {
      const row = await db.agentExecution.create({ data: {
        evaluationId: evaluation.id, agentType: agent.agentType, status: index === 0 ? "Running" : "Completed",
        createdAt: new Date("2026-11-01T00:00:00Z"),
        cancellationRequestedAt: index === 0 ? new Date() : null,
        result: index === 1 ? "invalid-json" : JSON.stringify({ run_id: `run-${index}`, attributes: ["security"], status: "partial",
          report: { executive_summary: large }, blackboard: large, docx_base64: large }),
        configurationSnapshot: JSON.stringify({ privateSettings: large, auditConfiguration: {
          version: 1, branch: "audited", commitHash: "a".repeat(40), attributes: ["security"], scopes: [{ content: large }],
        } }),
      } })
      ids.push(row.id)
    }
    const otherProject = await db.project.create({ data: { githubRepositoryId: 987655n, repositoryOwner: "acme", repositoryName: "other", status: "READY" } })
    const url = `/api/projects/${project.id}/audits`
    const repositoryPage = await new QualityAuditRepository(db).list(project.id, 2, 0)
    assert.equal(repositoryPage.items.length, 2)
    assert.ok(JSON.stringify(repositoryPage).length < 10000, "no full result or configuration crosses the repository boundary")
    assert.equal("result" in repositoryPage.items[0]!.row, false)

    const response = await app.inject({ url: `${url}?limit=2&offset=0` })
    assert.equal(response.statusCode, 200, response.body)
    const first = response.json()
    assert.equal(first.total, 7)
    assert.equal(first.hasRunning, true, "running audits outside this page must still drive polling")
    assert.deepEqual(first.items.map((item: { id: number }) => item.id), [ids[6], ids[5]])
    assert.equal(first.items[0].runId, "run-6")
    assert.equal(first.items[0].branch, "audited")
    assert.equal(first.items[0].commitHash, "a".repeat(40))
    assert.deepEqual(first.items[0].attributes, ["security"])
    assert.equal(first.items[0].configurationAvailable, true)
    assert.equal(first.items[0].reportAvailable, true)
    assert.ok(response.body.length < 5000)
    assert.ok(!response.body.includes("artifact-not-for-history"))

    const last = (await app.inject({ url: `${url}?limit=2&offset=6` })).json()
    assert.deepEqual(last.items.map((item: { id: number }) => item.id), [ids[0]])
    assert.equal(last.items[0].auditStatus, "cancelling")
    const clamped = (await app.inject({ url: `${url}?limit=2&offset=100` })).json()
    assert.equal(clamped.offset, 6)
    assert.equal(clamped.items.length, 1)
    const invalidResult = (await app.inject({ url: `${url}?limit=1&offset=5` })).json().items[0]
    assert.equal(invalidResult.reportAvailable, false)
    assert.equal(invalidResult.runId, null)

    const empty = (await app.inject({ url: `/api/projects/${otherProject.id}/audits?limit=5&offset=0` })).json()
    assert.deepEqual(empty, { items: [], total: 0, hasRunning: false, limit: 5, offset: 0 })
    assert.equal((await app.inject({ url: "/api/projects/999999/audits?limit=5" })).statusCode, 404)
    for (const query of ["limit=0", "limit=101", "limit=1.5", "offset=-1", "offset=2147483648"]) {
      assert.equal((await app.inject({ url: `${url}?${query}` })).statusCode, 400)
    }
    const legacy = (await app.inject({ url })).json()
    assert.equal(legacy.length, 7, "unpaginated clients retain the array contract")
    assert.equal(legacy[0].runId, "run-6")
  } finally {
    await app.close()
    await db.$disconnect()
  }
})

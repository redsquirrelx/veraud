import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, mkdir, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import Fastify from "fastify"
import { AuditArtifactStore, auditArtifactFormat, parseArtifactManifest } from "./audit-artifacts.js"
import { registerApiSchemas } from "../../infrastructure/openapi/registerApiSchemas.js"
import { registerQualityAuditRoutes } from "./quality-audit.controller.js"
import { QualityAuditService } from "./quality-audit.service.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"
import type { ProjectService } from "../project/project.service.js"

const runId = "a".repeat(32)
const COMMIT = "a".repeat(40)
const qualityResults = {
  findings: [{ id: "F-1", title: "Bypass", description: "Calls private state", kind: "violation",
    components: ["Service"], evidence_ids: ["E-1"], justification: "Direct access", severity: "high", confidence: 0.8,
    recommendation: "Use the interface", verification_status: "verified",
    criterion: { id: "C-1", description: "Encapsulation", origin: "explicit", provenance: "docs" } }],
}
const sections = [
  "identification", "executive_summary", "objectives_and_scope", "methodology_and_criteria", "software_description",
  "quality_results", "consolidated_risks", "general_conclusions", "recommendations_and_improvement_plan", "annexes_and_traceability",
]

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "veraud-artifacts-"))
  const target = join(root, runId)
  await mkdir(join(target, "sections"), { recursive: true })
  const report = JSON.stringify({ quality_results: qualityResults })
  const document = Buffer.from("PK-test-artifact")
  await writeFile(join(target, "report.json"), report)
  await writeFile(join(target, "report.docx"), document)
  await Promise.all(sections.map((section) =>
    writeFile(join(target, "sections", `${section}.json`), JSON.stringify(section === "quality_results" ? qualityResults : {}))))
  const manifest = { format: auditArtifactFormat, run_id: runId, report_bytes: Buffer.byteLength(report), docx_bytes: document.byteLength, sections }
  const row = { id: 7, agentType: "maintainability_manager", status: "Completed", result: JSON.stringify({
    attributes: ["maintainability"], status: "completed", run_id: runId, error_detail: null, artifacts: manifest,
  }), evaluation: { projectVersion: { branch: "main", commitHash: COMMIT } } }
  const repository = {
    find: async (projectId: number, id: number) => projectId === 2 && id === 7 ? row : null,
    findReportSection: async () => ({ reportType: null, data: null }),
  } as unknown as QualityAuditRepository
  const calls: unknown[] = []
  const executions = { openFindingResolution: async (...args: unknown[]) => { calls.push(args); return { id: 99 } } } as unknown as AgentExecutionService
  const service = new QualityAuditService(repository, {} as ProjectService, executions, undefined, undefined, new AuditArtifactStore(undefined, root))
  return { service, calls, target }
}

describe("quality audit filesystem artifacts", () => {
  it("serves compact execution issues and enforces project ownership", async () => {
    const { service, target } = await fixture()
    const issues = [{ agent_id: "test_isolation", termination_reason: "provider_daily_quota_exhausted",
      explanation: "Daily quota exhausted", incidents: ["HTTP 429"], diagnostics: ["quota_window=day"] }]
    await writeFile(join(target, "sections", "annexes_and_traceability.json"), JSON.stringify({
      evidence_inventory: ["private evidence".repeat(100000)], execution_issues: issues,
    }))
    const app = Fastify({ logger: false })
    registerApiSchemas(app)
    registerQualityAuditRoutes(app, service)
    try {
      const response = await app.inject({ url: "/api/projects/2/audits/7/execution-issues" })
      assert.equal(response.statusCode, 200)
      assert.equal(response.body.length < 2000, true)
      assert.equal(response.body.includes("private evidence"), false)
      assert.equal(response.json().execution_issues[0].termination_reason, "provider_daily_quota_exhausted")
      assert.equal((await app.inject({ url: "/api/projects/99/audits/7/execution-issues" })).statusCode, 404)
    } finally { await app.close() }
  })

  it("validates compact artifacts and serves only the selected section", async () => {
    assert.deepEqual(parseArtifactManifest({ format: auditArtifactFormat, run_id: runId, report_bytes: 1, docx_bytes: 1, sections: [] }), {
      format: auditArtifactFormat, run_id: runId, report_bytes: 1, docx_bytes: 1, sections: [] })
    assert.equal(parseArtifactManifest({ format: auditArtifactFormat, run_id: "../escape", report_bytes: 1, docx_bytes: 1, sections: [] }), null)
    const { service } = await fixture()
    const section = await service.reportSection(2, 7, "quality_results")
    assert.deepEqual(section.data, qualityResults)
    assert.match((await service.reportFile(2, 7))?.replaceAll("\\", "/") ?? "", new RegExp(`${runId}/report\\.json$`))
    assert.match((await service.documentFile(2, 7))?.replaceAll("\\", "/") ?? "", new RegExp(`${runId}/report\\.docx$`))
  })

  it("streams report JSON and DOCX without materializing the artifacts in Node memory", async () => {
    const { service } = await fixture()
    const app = Fastify({ logger: false })
    registerApiSchemas(app)
    registerQualityAuditRoutes(app, service)
    const report = await app.inject({ method: "GET", url: "/api/projects/2/audits/7/report" })
    assert.equal(report.statusCode, 200)
    assert.equal(report.headers["content-type"]?.startsWith("application/json"), true)
    assert.equal(JSON.parse(report.body).quality_results.findings[0].id, "F-1")
    const document = await app.inject({ method: "GET", url: "/api/projects/2/audits/7/report.docx" })
    assert.equal(document.statusCode, 200)
    assert.equal(document.body.startsWith("PK"), true)
    await app.close()
  })

  it("revalidates findings from the quality section instead of an embedded DOCX", async () => {
    const { service, calls } = await fixture()
    const execution = await service.startFindingResolution(2, 7, COMMIT, ["F-1"])
    assert.equal(execution.id, 99)
    assert.equal((calls[0] as [number, string, string, Array<Record<string, unknown>>, number])[3][0]?.id, "F-1")
  })
})

import { it } from "node:test"
import assert from "node:assert/strict"
import { QualityAuditService } from "./quality-audit.service.js"
import { InvalidGitRequestError } from "../project/project.service.js"
import { findingResolutionFindings } from "./finding-resolution.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import type { ProjectService } from "../project/project.service.js"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"

const COMMIT = "a".repeat(40)

function report() {
  return {
    quality_results: {
      findings: [{
        id: "F-1", title: "Bypass", description: "Calls private state", kind: "violation",
        components: ["Service"], evidence_ids: ["E-1"], justification: "Direct access",
        modularity_impact: "Coupling", severity: "high", confidence: 0.9,
        recommendation: "Use the interface", verification_status: "verified",
        criterion: { id: "C-1", description: "Encapsulation", origin: "explicit", provenance: "docs" },
      }, {
        id: "F-2", title: "Observation", description: "Potential overlap", kind: "design_observation",
        components: ["Other"], severity: "low", verification_status: "pending",
        criterion: { id: "C-2", description: "Cohesion", origin: "inferred", provenance: "report" },
      }],
    },
  }
}

function fixture(commit = COMMIT) {
  const row = { id: 7, agentType: "maintainability_manager", status: "Completed", result: JSON.stringify({ report: report() }),
    evaluation: { projectVersion: { branch: "main", commitHash: commit } } }
  const calls: unknown[] = []
  const repository = { find: async (projectId: number, id: number) => projectId === 2 && id === 7 ? row : null } as unknown as QualityAuditRepository
  const executions = { openFindingResolution: async (...args: unknown[]) => { calls.push(args); return { id: 99 } } } as unknown as AgentExecutionService
  const service = new QualityAuditService(repository, {} as ProjectService, executions)
  return { service, calls }
}

it("maps persisted report findings and starts the standalone execution", async () => {
  const f = fixture()
  const execution = await f.service.startFindingResolution(2, 7, COMMIT, ["F-1"])
  assert.equal(execution.id, 99)
  const [, branch, commit, findings, auditId] = f.calls[0] as [number, string, string, Array<Record<string, unknown>>, number]
  assert.equal(branch, "main")
  assert.equal(commit, COMMIT)
  assert.equal(auditId, 7)
  assert.equal(findings.length, 1)
  assert.equal(findings[0]!.id, "F-1")
  assert.equal(findings[0]!.kind, "violation")
  assert.equal(findings[0]!.validation_status, "accepted")
})

it("refuses a commit other than the audited revision", async () => {
  const f = fixture()
  await assert.rejects(f.service.startFindingResolution(2, 7, "b".repeat(40)), InvalidGitRequestError)
})

it("refuses unknown finding selections", async () => {
  const f = fixture()
  await assert.rejects(f.service.startFindingResolution(2, 7, COMMIT, ["missing"]), InvalidGitRequestError)
})

it("maps the persisted report without forwarding historical evidence bodies", () => {
  const findings = findingResolutionFindings(report())
  assert.equal(findings.length, 2)
  assert.deepEqual(findings[0]!.evidence, [])
  assert.equal(findings[1]!.validation_status, "insufficient_evidence")
})

import { Link } from "react-router-dom"
import { Card } from "../../shared/ui-kit/index.ts"
import {
  OrientationResultView,
  ProjectArchitectureResultView,
  SemanticValidationResultView,
  StageStatusView,
} from "../../features/project-management/PipelineResult.tsx"
import {
  parseOrientationResult,
  parseProjectArchitectureResult,
  parseSemanticValidationResult,
} from "../../features/project-management/pipelineResult.ts"
import "./TestStageShowcasePage.css"

const orientationJson = JSON.stringify({
  completion_status: "complete",
  orientation: {
    project_type: { statement: "A layered web service.", status: "supported", evidence_ids: ["e1", "e2"] },
    purpose: { statement: "Serve the audit API.", status: "supported", evidence_ids: ["e2"] },
    components: [
      { name: "api", file_ids: ["f1", "f2"], responsibility: { statement: "HTTP surface.", status: "supported", evidence_ids: ["e1"] } },
      { name: "core", file_ids: ["f3"], responsibility: { statement: "Audit orchestration.", status: "supported", evidence_ids: ["e2"] } },
      { name: "store", file_ids: ["f4"], responsibility: { statement: "Likely persistence.", status: "hypothesis", limitations: ["Only imports seen."] } },
    ],
    starting_points: [
      { file_id: "f1", reason: "Router: every request enters here." },
      { file_id: "f3", reason: "Pipeline entry point." },
    ],
    uncertainties: ["Background jobs unclear.", "Auth flow not found."],
  },
})

const architectureJson = JSON.stringify({
  completion_status: "partial",
  architecture: {
    organization: [
      { name: "api", file_ids: ["f1"], responsibility: { statement: "HTTP surface.", status: "supported", evidence_ids: ["e1"] } },
      { name: "core", file_ids: ["f3"], responsibility: { statement: "Audit orchestration.", status: "supported", evidence_ids: ["e2"] } },
      { name: "store", file_ids: ["f4"], responsibility: { statement: "Persistence?", status: "unresolved", limitations: ["No writes observed."] } },
    ],
    connections: [
      { source_unit: "api", target_unit: "core", description: { statement: "Routes delegate to the pipeline.", status: "supported", evidence_ids: ["e1"] } },
      { source_unit: "core", target_unit: "store", description: { statement: "Core persists runs.", status: "hypothesis", limitations: ["Inferred from imports."] } },
    ],
    closest_architecture: { pattern: "layered", assessment: { statement: "Three visible layers.", status: "supported", evidence_ids: ["e1"] } },
    deviations: [{ observed_decision: { statement: "API imports store directly.", status: "supported", evidence_ids: ["e1"] }, pattern_expectation: "Layers talk downwards only.", explanation: "Shortcut for reads." }],
    infrastructure: [
      { name: "postgres", kind: "state", configured: { statement: "DATABASE_URL set.", status: "supported", evidence_ids: ["e1"] } },
      { name: "redis", kind: "communication" },
    ],
    uncertainties: ["Queue backend unknown."],
    diagram: {
      title: "Components",
      scope: "repo",
      groups: [{ id: "svc", title: "Service", scope: "runtime" }],
      nodes: [
        { id: "api", unit_ref: "/organization/0" },
        { id: "core", unit_ref: "/organization/1" },
        { id: "store", unit_ref: "/organization/2", group_id: "svc" },
      ],
      edges: [{ source: "api", target: "core", claim_ref: "calls", kind: "calls" }],
    },
  },
  limitations: ["Snapshot capped at 5000 files."],
})

const validationJson = JSON.stringify({
  completion_status: "partial",
  verdict: "needs_evidence",
  selected_target_ids: ["/organization/0/responsibility", "/organization/1/responsibility", "/organization/2/responsibility"],
  pending_target_ids: ["/organization/2/responsibility"],
  findings: [
    {
      target_id: "/organization/0/responsibility",
      checked_statement: "HTTP surface.",
      verdict: "supported",
      reason: "Routes inspected end to end.",
      counterevidence_check: "No contradicting handler found.",
      evidence_ids: ["e1"],
    },
    {
      target_id: "/organization/1/responsibility",
      checked_statement: "Audit orchestration.",
      verdict: "contradicted",
      reason: "Orchestration lives in the worker, not core.",
      counterevidence_check: "Worker module owns the graph.",
      evidence_ids: ["e2"],
      correction: { statement: "Worker owns orchestration.", scope: "core", status: "supported", evidence_ids: ["e2"] },
    },
  ],
})

function parsed<T>(parse: (result: string | null) => T | null, result: string): T {
  const summary = parse(result)
  if (summary === null) {
    throw new Error("Showcase fixture failed to parse")
  }
  return summary
}

export function TestStageShowcasePage() {
  return (
    <section className="test-stage-showcase-page">
      <h1>Stage showcase</h1>
      <p className="label">
        <Link to="/test">All playgrounds</Link> · compact stage views with realistic multi-item payloads
      </p>
      <Card>
        <OrientationResultView summary={parsed(parseOrientationResult, orientationJson)} />
      </Card>
      <Card>
        <ProjectArchitectureResultView summary={parsed(parseProjectArchitectureResult, architectureJson)} />
      </Card>
      <Card>
        <SemanticValidationResultView summary={parsed(parseSemanticValidationResult, validationJson)} />
      </Card>
      <Card>
        <span className="label">Failed run without a report</span>
        <StageStatusView
          title="Architecture"
          result={JSON.stringify({
            completion_status: "failed",
            architecture: null,
            limitations: ["Snapshot capped at 5000 files."],
            execution_issues: [{ id: "issue:1", stage: "architecture", category: "call_limit", message: "Model-call limit reached." }],
          })}
        />
      </Card>
    </section>
  )
}

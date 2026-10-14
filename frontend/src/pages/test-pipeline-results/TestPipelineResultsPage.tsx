import { Link } from "react-router-dom"
import { Card } from "../../shared/ui-kit/index.ts"
import {
  AnalyzerResultView,
  ArchitectureResultView,
  OrientationResultView,
  ProjectArchitectureResultView,
  SemanticValidationResultView,
} from "../../features/project-management/PipelineResult.tsx"
import {
  parseAnalyzerResult,
  parseArchitectureResult,
  parseOrientationResult,
  parseProjectArchitectureResult,
  parseSemanticValidationResult,
} from "../../features/project-management/pipelineResult.ts"
import "./TestPipelineResultsPage.css"

const orientationJson = JSON.stringify({
  completion_status: "complete",
  orientation: {
    project_type: { statement: "A command-line tool.", status: "supported", evidence_ids: ["e1"] },
    purpose: { statement: "Audit repositories.", status: "hypothesis", limitations: ["Single file inspected."] },
    components: [{ name: "core", file_ids: ["f1"], responsibility: { statement: "Runs the audit.", status: "supported", evidence_ids: ["e1"] } }],
    starting_points: [{ file_id: "f1", reason: "Entry point." }],
    uncertainties: ["Plugin system unclear."],
  },
})

const architectureJson = JSON.stringify({
  completion_status: "complete",
  architecture: {
    organization: [{ name: "core", file_ids: ["f1"], responsibility: { statement: "Runs the audit.", status: "supported", evidence_ids: ["e1"] } }],
    connections: [{ source_unit: "core", target_unit: "cli", description: { statement: "Core drives the CLI.", status: "supported", evidence_ids: ["e1"] } }],
    closest_architecture: { pattern: "layered", assessment: { statement: "Layers are visible.", status: "supported", evidence_ids: ["e1"] } },
    deviations: [{ observed_decision: { statement: "CLI imports core internals.", status: "hypothesis", limitations: ["Partial read."] }, pattern_expectation: "Depend on ports.", explanation: "Shortcut for speed." }],
    infrastructure: [{ name: "sqlite", kind: "state", configured: { statement: "File database.", status: "supported", evidence_ids: ["e1"] } }],
    uncertainties: [],
    diagram: { title: "Components", scope: "repo", nodes: [{ id: "core", unit_ref: "/organization/0" }], edges: [] },
  },
})

const validationJson = JSON.stringify({
  completion_status: "complete",
  verdict: "revisions_needed",
  selected_target_ids: ["/organization/0/responsibility"],
  pending_target_ids: [],
  findings: [{
    target_id: "/organization/0/responsibility",
    checked_statement: "Runs the audit.",
    verdict: "overstated",
    reason: "Only the happy path was inspected.",
    evidence_ids: ["e1"],
    correction: { statement: "Runs the happy-path audit.", scope: "core", status: "hypothesis", evidence_ids: ["e1"], limitations: ["Single file."] },
  }],
})

const legacyAnalysis = JSON.stringify({
  kind: "library",
  summary: "A widget library.",
  primary_language: "python",
  entrypoints: ["main.py"],
  key_components: ["pkg/core.py"],
  confidence: "high",
  files_read: 4,
  hypothesis_confirmed: true,
})

const legacyDescription = JSON.stringify({
  style: "layered",
  intended_style: "hexagonal",
  deviations: [],
  components: [{ path: "pkg/core.py", responsibility: "Holds the core logic." }],
  data_flow: "Execution starts at main and reaches core.",
  third_party: [],
  cycles: [],
  quality_notes: [],
  risks: [],
  confidence: "medium",
})

function parsed<T>(parse: (result: string | null) => T | null, result: string): T {
  const summary = parse(result)
  if (summary === null) {
    throw new Error("Playground fixture failed to parse")
  }
  return summary
}

export function TestPipelineResultsPage() {
  return (
    <section className="test-pipeline-results-page">
      <h1>Pipeline results playground</h1>
      <p className="label">
        <Link to="/test">All playgrounds</Link>
      </p>
      <Card>
        <span className="label">Orientation</span>
        <OrientationResultView summary={parsed(parseOrientationResult, orientationJson)} />
      </Card>
      <Card>
        <span className="label">Project architecture</span>
        <ProjectArchitectureResultView summary={parsed(parseProjectArchitectureResult, architectureJson)} />
      </Card>
      <Card>
        <span className="label">Semantic validation</span>
        <SemanticValidationResultView summary={parsed(parseSemanticValidationResult, validationJson)} />
      </Card>
      <Card>
        <span className="label">Legacy analyzer + architect (unchanged)</span>
        <AnalyzerResultView summary={parsed(parseAnalyzerResult, legacyAnalysis)} />
        <ArchitectureResultView description={parsed(parseArchitectureResult, legacyDescription)} />
      </Card>
      <Card>
        <span className="label">Unparseable payloads fall back to run status</span>
        <p className="mono">{String(parseOrientationResult("not json"))} / {String(parseSemanticValidationResult(null))}</p>
      </Card>
    </section>
  )
}

import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import {
  OrientationResultView,
  PipelineRunStatus,
  ProjectArchitectureResultView,
  SemanticValidationResultView,
  StageStatusView,
} from "./PipelineResult.tsx"
import {
  parseOrientationResult,
  parseProjectArchitectureResult,
  parseSemanticValidationResult,
  parseStageStatus,
} from "./pipelineResult.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

function execution(overrides: Record<string, unknown> = {}): AgentExecution {
  return {
    id: 12,
    evaluationId: 7,
    agentType: "semantic_validation",
    status: "Completed",
    result: validation,
    error: null,
    inputTokens: null,
    outputTokens: null,
    createdAt: "2026-01-01",
    startedAt: "2026-01-01",
    finishedAt: "2026-01-01",
    ...overrides,
  }
}

describe("PipelineRunStatus", () => {
  it("shows the run and its failure error", () => {
    render(<PipelineRunStatus execution={execution({ status: "Failed", error: "boom", result: null })} />)
    expect(screen.getByText("Failed")).toBeDefined()
    expect(screen.getByText("semantic_validation run #12")).toBeDefined()
    expect(screen.getByText("boom")).toBeDefined()
  })
})

const orientation = JSON.stringify({
  completion_status: "complete",
  orientation: {
    project_type: { statement: "A command-line tool.", status: "supported", evidence_ids: ["e1"] },
    purpose: { statement: "Audit repositories.", status: "hypothesis", limitations: ["Single file inspected."] },
    components: [
      { name: "core", file_ids: ["f1"], responsibility: { statement: "Runs the audit.", status: "supported", evidence_ids: ["e1"] } },
      { name: "", file_ids: ["f2"], responsibility: { statement: "Ghost.", status: "supported", evidence_ids: ["e2"] } },
    ],
    starting_points: [{ file_id: "f1", reason: "Entry point." }],
    uncertainties: ["Plugin system unclear.", ""],
  },
})

const projectArchitecture = JSON.stringify({
  completion_status: "partial",
  architecture: {
    organization: [{ name: "core", file_ids: ["f1"], responsibility: { statement: "Runs the audit.", status: "supported", evidence_ids: ["e1"] } }],
    connections: [
      { source_unit: "core", target_unit: "cli", description: { statement: "Core drives the CLI.", status: "supported", evidence_ids: ["e1"] } },
      { source_unit: "", target_unit: "cli", description: { statement: "Ghost.", status: "supported", evidence_ids: ["e1"] } },
    ],
    closest_architecture: { pattern: "layered", assessment: { statement: "Layers are visible.", status: "supported", evidence_ids: ["e1"] } },
    deviations: [{ observed_decision: { statement: "CLI imports core internals.", status: "hypothesis", limitations: ["Partial read."] }, pattern_expectation: "Depend on ports.", explanation: "Shortcut for speed." }],
    infrastructure: [{ name: "sqlite", kind: "state" }, { name: "", kind: "state" }],
    uncertainties: [],
    diagram: { title: "Components", scope: "repo", nodes: [{ id: "core", unit_ref: "/organization/0" }], edges: [] },
  },
})

const projectArchitectureWithDiagram = JSON.stringify({
  ...JSON.parse(projectArchitecture),
  architecture_diagram: {
    mermaid: "flowchart LR\n  core[core]",
    report_origin: "original",
    report_hash: "abc123",
  },
})

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (_id: string, chart: string) => ({ svg: `<svg>${chart}</svg>`, diagramType: "flowchart" })),
  },
}))

const validation = JSON.stringify({
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

describe("parseOrientationResult", () => {
  it("parses the orientation verdict dropping empty entries", () => {
    const parsed = parseOrientationResult(orientation)
    expect(parsed?.completionStatus).toBe("complete")
    expect(parsed?.projectType).toBe("A command-line tool.")
    expect(parsed?.projectTypeStatus).toBe("supported")
    expect(parsed?.purpose).toBe("Audit repositories.")
    expect(parsed?.components).toEqual([{ name: "core", responsibility: "Runs the audit.", status: "supported" }])
    expect(parsed?.startingPoints).toEqual([{ fileId: "f1", reason: "Entry point." }])
    expect(parsed?.uncertainties).toEqual(["Plugin system unclear."])
  })

  it("rejects malformed payloads and missing orientation", () => {
    expect(parseOrientationResult(null)).toBeNull()
    expect(parseOrientationResult("not json")).toBeNull()
    expect(parseOrientationResult(JSON.stringify({ completion_status: "nope", orientation: {} }))).toBeNull()
    expect(parseOrientationResult(JSON.stringify({ completion_status: "complete" }))).toBeNull()
  })
})

describe("parseProjectArchitectureResult", () => {
  it("parses units, connections, classification and diagram shape", () => {
    const parsed = parseProjectArchitectureResult(projectArchitecture)
    expect(parsed?.completionStatus).toBe("partial")
    expect(parsed?.units).toEqual([{ name: "core", responsibility: "Runs the audit.", status: "supported" }])
    expect(parsed?.connections).toEqual([{ from: "core", to: "cli", description: "Core drives the CLI." }])
    expect(parsed?.pattern).toBe("layered")
    expect(parsed?.patternAssessment).toBe("Layers are visible.")
    expect(parsed?.deviations).toEqual([{
      decision: "CLI imports core internals.",
      expectation: "Depend on ports.",
      explanation: "Shortcut for speed.",
    }])
    expect(parsed?.infrastructure).toEqual([{ name: "sqlite", kind: "state" }])
    expect(parsed?.diagramTitle).toBe("Components")
    expect(parsed?.diagramNodes).toBe(1)
    expect(parsed?.diagramEdges).toBe(0)
    expect(parsed?.diagramMermaid).toBe("")
    expect(parsed?.diagramOrigin).toBe("")
  })

  it("parses the merged pipeline mermaid and ignores malformed diagram payloads", () => {
    const parsed = parseProjectArchitectureResult(projectArchitectureWithDiagram)
    expect(parsed?.diagramMermaid).toBe("flowchart LR\n  core[core]")
    expect(parsed?.diagramOrigin).toBe("original")
    const malformed = parseProjectArchitectureResult(JSON.stringify({
      ...JSON.parse(projectArchitecture),
      architecture_diagram: { mermaid: 42, report_origin: "original" },
    }))
    expect(malformed?.diagramMermaid).toBe("")
    const blank = parseProjectArchitectureResult(JSON.stringify({
      ...JSON.parse(projectArchitecture),
      architecture_diagram: { mermaid: "   ", report_origin: "original" },
    }))
    expect(blank?.diagramMermaid).toBe("")
  })

  it("rejects malformed payloads and missing reports", () => {
    expect(parseProjectArchitectureResult(null)).toBeNull()
    expect(parseProjectArchitectureResult("not json")).toBeNull()
    expect(parseProjectArchitectureResult(JSON.stringify({ completion_status: "complete" }))).toBeNull()
  })
})

describe("parseSemanticValidationResult", () => {  it("parses verdict, findings and corrections", () => {
    const parsed = parseSemanticValidationResult(validation)
    expect(parsed?.completionStatus).toBe("complete")
    expect(parsed?.verdict).toBe("revisions_needed")
    expect(parsed?.findings).toEqual([{
      targetId: "/organization/0/responsibility",
      statement: "Runs the audit.",
      verdict: "overstated",
      reason: "Only the happy path was inspected.",
      correction: "Runs the happy-path audit.",
    }])
    expect(parsed?.pending).toEqual([])
  })

  it("rejects unknown verdicts and malformed payloads", () => {
    expect(parseSemanticValidationResult(null)).toBeNull()
    expect(parseSemanticValidationResult("not json")).toBeNull()
    expect(parseSemanticValidationResult(JSON.stringify({ completion_status: "complete", verdict: "nope" }))).toBeNull()
  })
})

describe("OrientationResultView", () => {
  it("renders type, purpose, components and starting points", () => {
    const summary = parseOrientationResult(orientation)
    if (summary === null) {
      throw new Error("orientation fixture must parse")
    }
    render(<OrientationResultView summary={summary} />)
    expect(screen.getByText("Orientation")).toBeDefined()
    expect(screen.getByText("A command-line tool.")).toBeDefined()
    expect(screen.getByText("Audit repositories.", { exact: false })).toBeDefined()
    expect(screen.getByText("core")).toBeDefined()
    expect(screen.getByText("Entry point.", { exact: false })).toBeDefined()
    expect(screen.getByText("Plugin system unclear.")).toBeDefined()
  })
})

describe("ProjectArchitectureResultView", () => {
  it("renders independent diagram views with external color legends and deviation details", () => {
    const report = JSON.parse(projectArchitectureWithDiagram)
    const legend = [{ layer: "architect", status: "supported", color: "#dbeafe" }]
    report.architecture_diagram.structure = { title: "Structure view", scope: "Application" }
    report.architecture_diagram.legend = legend
    report.architecture_diagram.deviation_notes = [{ id: "D1", observation: "Direct adapter coupling", expectation: "Depend on a port", explanation: "The use case bypasses its contract." }]
    report.architecture_diagram.views = [{ structure: { title: "Dependency view", scope: "Contracts" }, mermaid: "flowchart TB\n  port[Port]", legend }]
    const summary = parseProjectArchitectureResult(JSON.stringify(report))!
    expect(summary.diagramViews).toHaveLength(2)
    expect(summary.diagramViews[0]?.mermaid).not.toBe(summary.diagramViews[1]?.mermaid)
    render(<ProjectArchitectureResultView summary={summary} />)
    expect(screen.getByRole("region", { name: "Structure view" })).toBeDefined()
    expect(screen.getByRole("region", { name: "Dependency view" })).toBeDefined()
    expect(screen.getAllByText("Color legend")).toHaveLength(2)
    expect(screen.getByText("Direct adapter coupling", { exact: false })).toBeDefined()
    expect(screen.getByText("Expected: Depend on a port")).toBeDefined()
    expect(screen.getAllByText(/Unreviewed does not mean rejected/)).toHaveLength(2)
  })
  it("shows the developed explanation, independent findings and pattern contrast", () => {
    const report = JSON.parse(projectArchitecture)
    report.architecture.explanation = { statement: "The inspected layers separate orchestration from persistence.", status: "supported" }
    report.relationship_coverage = [{ unit_name: "core", status: "unresolved", reason: "The persistence boundary needs inspection.", pending_paths: ["store.py"] }]
    report.architecture.supporting_evidence = [{ statement: "The service consumes the repository contract.", status: "hypothesis", scope: "service", limitations: ["Other flows remain uninspected."] }]
    report.architecture.closest_architecture.contrast_question = "Does the service import a concrete adapter?"
    report.architecture.closest_architecture.contrast_result = { statement: "The inspected operation uses the contract.", status: "supported" }
    const summary = parseProjectArchitectureResult(JSON.stringify(report))!
    render(<ProjectArchitectureResultView summary={summary} />)
    expect(screen.getByText("The inspected layers separate orchestration from persistence.")).toBeDefined()
    expect(screen.getByText("Module relationship coverage (1)")).toBeDefined()
    expect(screen.getByText("The persistence boundary needs inspection.")).toBeDefined()
    expect(screen.getByText("Pending endpoints (1): store.py")).toBeDefined()
    expect(screen.getByText("Supporting findings (1)")).toBeDefined()
    expect(screen.getByText("The service consumes the repository contract.")).toBeDefined()
    expect(screen.getByText("Scope: service")).toBeDefined()
    expect(screen.getByText("Other flows remain uninspected.")).toBeDefined()
    expect(screen.getByText("Does the service import a concrete adapter?")).toBeDefined()
    expect(screen.getByText("The inspected operation uses the contract.")).toBeDefined()
  })
  it("renders units, connections, pattern and diagram shape", () => {
    const summary = parseProjectArchitectureResult(projectArchitecture)
    if (summary === null) {
      throw new Error("architecture fixture must parse")
    }
    render(<ProjectArchitectureResultView summary={summary} execution={execution({ agentType: "architecture" })} />)
    expect(screen.getByText("Architecture")).toBeDefined()
    expect(screen.getByText("architecture run #12")).toBeDefined()
    expect(screen.getByText("layered")).toBeDefined()
    expect(screen.getByText("Layers are visible.")).toBeDefined()
    expect(screen.getByText("core drives the CLI.", { exact: false })).toBeDefined()
    expect(screen.getByText("CLI imports core internals.", { exact: false })).toBeDefined()
    expect(screen.getByText("sqlite")).toBeDefined()
    expect(screen.getByText("Diagram “Components”: 1 node(s), 0 edge(s)", { exact: false })).toBeDefined()
  })

  it("renders the merged mermaid diagram instead of the shape footnote", () => {
    const summary = parseProjectArchitectureResult(projectArchitectureWithDiagram)
    if (summary === null) {
      throw new Error("architecture diagram fixture must parse")
    }
    render(<ProjectArchitectureResultView summary={summary} />)
    expect(screen.getByText("Diagram (original report)", { exact: false })).toBeDefined()
    expect(screen.queryByText("1 node(s)", { exact: false })).toBeNull()
  })
})

describe("SemanticValidationResultView", () => {
  it("renders verdict, findings and corrections", () => {
    const summary = parseSemanticValidationResult(validation)
    if (summary === null) {
      throw new Error("validation fixture must parse")
    }
    render(<SemanticValidationResultView summary={summary} />)
    expect(screen.getByText("Semantic validation")).toBeDefined()
    expect(screen.getByText("revisions_needed")).toBeDefined()
    expect(screen.getByText("overstated")).toBeDefined()
    expect(screen.getByText("Only the happy path was inspected.", { exact: false })).toBeDefined()
    expect(screen.getByText("Proposed correction: Runs the happy-path audit.", { exact: false })).toBeDefined()
  })
})

describe("parseStageStatus", () => {
  it("explains failed runs without a report", () => {
    const parsed = parseStageStatus(JSON.stringify({
      completion_status: "failed",
      architecture: null,
      limitations: ["Snapshot capped."],
      execution_issues: [
        { id: "issue:1", stage: "architecture", category: "call_limit", message: "Model-call limit reached." },
        { id: "issue:2", stage: "architecture", category: "", message: "" },
      ],
    }))
    expect(parsed).toEqual({
      completionStatus: "failed",
      issues: [{ category: "call_limit", message: "Model-call limit reached." }],
      limitations: ["Snapshot capped."],
    })
  })

  it("rejects payloads without a completion status", () => {
    expect(parseStageStatus(null)).toBeNull()
    expect(parseStageStatus("not json")).toBeNull()
    expect(parseStageStatus(JSON.stringify({ architecture: null }))).toBeNull()
  })
})

describe("StageStatusView", () => {
  it("renders issues and limitations with a bare-status fallback", () => {
    const failed = JSON.stringify({
      completion_status: "failed",
      architecture: null,
      limitations: ["Snapshot capped."],
      execution_issues: [{ id: "issue:1", stage: "architecture", category: "call_limit", message: "Model-call limit reached." }],
    })
    render(<StageStatusView title="Architecture" result={failed} execution={execution({ agentType: "architecture", status: "Completed" })} />)
    expect(screen.getByText("Architecture")).toBeDefined()
    expect(screen.getByText("failed")).toBeDefined()
    expect(screen.getByText("call_limit")).toBeDefined()
    expect(screen.getByText("Model-call limit reached.", { exact: false })).toBeDefined()
    expect(screen.getByText("Snapshot capped.")).toBeDefined()
  })

  it("falls back to the run status when nothing parses", () => {
    render(<StageStatusView title="Architecture" result={null} execution={execution({ agentType: "architecture", status: "Waiting" })} />)
    expect(screen.getByText("architecture run #12")).toBeDefined()
    expect(screen.queryByText("Issues (")).toBeNull()
  })
})

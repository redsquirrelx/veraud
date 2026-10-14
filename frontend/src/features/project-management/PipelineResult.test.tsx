import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import {
  AnalyzerResultView,
  ArchitectureResultView,
  OrientationResultView,
  PipelineRunStatus,
  ProjectArchitectureResultView,
  SemanticValidationResultView,
  StageStatusView,
} from "./PipelineResult.tsx"
import {
  parseAnalyzerResult,
  parseArchitectureResult,
  parseOrientationResult,
  parseProjectArchitectureResult,
  parseSemanticValidationResult,
  parseStageStatus,
} from "./pipelineResult.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

const analysis = JSON.stringify({
  kind: "library",
  summary: "A widget library.",
  primary_language: "python",
  entrypoints: ["main.py"],
  key_components: ["pkg/core.py"],
  confidence: "high",
  files_read: 4,
  read_rounds: 1,
  hypothesis_confirmed: true,
})

const description = JSON.stringify({
  style: "layered",
  intended_style: "hexagonal",  deviations: [{ observation: "Handlers skip the port.", evidence: ["api/handler.py"] }],
  components: [{ path: "pkg/core.py", responsibility: "Holds the core logic." }],
  data_flow: "Execution starts at main and reaches core.",
  third_party: ["requests"],
  cycles: [["a.py", "b.py"]],
  quality_notes: [{ characteristic: "modularity", observation: "One job per module.", evidence: ["pkg/core.py"] }],
  risks: ["Circular imports: a.py ↔ b.py"],
  confidence: "medium",
})

function execution(overrides: Record<string, unknown> = {}): AgentExecution {
  return {
    id: 12,
    evaluationId: 7,
    agentType: "architect",
    status: "Completed",
    result: description,
    error: null,
    inputTokens: null,
    outputTokens: null,
    createdAt: "2026-01-01",
    startedAt: "2026-01-01",
    finishedAt: "2026-01-01",
    ...overrides,
  }
}

describe("parseAnalyzerResult", () => {
  it("parses the full verdict", () => {
    expect(parseAnalyzerResult(analysis)).toEqual({
      kind: "library",
      confidence: "high",
      summary: "A widget library.",
      primaryLanguage: "python",
      entrypoints: ["main.py"],
      keyComponents: ["pkg/core.py"],
      filesRead: 4,
      hypothesisConfirmed: true,
    })
  })

  it("rejects unknown kinds, bad confidence and malformed JSON", () => {
    expect(parseAnalyzerResult(null)).toBeNull()
    expect(parseAnalyzerResult("not json")).toBeNull()
    expect(parseAnalyzerResult(JSON.stringify({ kind: "nope", confidence: "high" }))).toBeNull()
    expect(parseAnalyzerResult(JSON.stringify({ kind: "library", confidence: "nope" }))).toBeNull()
  })
})

describe("parseArchitectureResult", () => {
  it("parses the full description", () => {
    const parsed = parseArchitectureResult(description)
    expect(parsed?.style).toBe("layered")
    expect(parsed?.intendedStyle).toBe("hexagonal")
    expect(parsed?.deviations).toEqual([{ observation: "Handlers skip the port.", evidence: ["api/handler.py"] }])
    expect(parsed?.components).toEqual([{ path: "pkg/core.py", responsibility: "Holds the core logic." }])
    expect(parsed?.dataFlow).toBe("Execution starts at main and reaches core.")
    expect(parsed?.thirdParty).toEqual(["requests"])
    expect(parsed?.cycles).toEqual([["a.py", "b.py"]])
    expect(parsed?.qualityNotes).toEqual([
      { characteristic: "modularity", observation: "One job per module.", evidence: ["pkg/core.py"] },
    ])
    expect(parsed?.risks).toEqual(["Circular imports: a.py ↔ b.py"])
    expect(parsed?.confidence).toBe("medium")
    expect(parsed?.diagramContainers).toBe("")
    expect(parsed?.diagramComponents).toBe("")
  })

  it("drops off-vocabulary notes and empty entries", () => {
    const parsed = parseArchitectureResult(JSON.stringify({
      style: "layered",
      confidence: "low",
      components: [{ path: "", responsibility: "ghost" }, { path: "a.py", responsibility: "" }],
      quality_notes: [
        { characteristic: "security", observation: "Uses eval.", evidence: ["a.py"] },
        { characteristic: "modularity", observation: "  ", evidence: ["a.py"] },
        { characteristic: "modularity", observation: "One job.", evidence: ["a.py"] },
      ],
      risks: ["  Real risk.  ", ""],
      cycles: [["only.py"]],
    }))
    expect(parsed?.components).toEqual([{ path: "a.py", responsibility: "" }])
    expect(parsed?.qualityNotes).toEqual([
      { characteristic: "modularity", observation: "One job.", evidence: ["a.py"] },
    ])
    expect(parsed?.risks).toEqual(["Real risk."])
    expect(parsed?.cycles).toEqual([])
  })

  it("parses diagram blocks when present", () => {
    const parsed = parseArchitectureResult(JSON.stringify({
      style: "layered",
      confidence: "low",
      diagram_containers: "flowchart LR",
      diagram_components: "",
    }))

    expect(parsed?.diagramContainers).toBe("flowchart LR")
    expect(parsed?.diagramComponents).toBe("")
  })

  it("rejects bad confidence and malformed JSON", () => {
    expect(parseArchitectureResult(null)).toBeNull()
    expect(parseArchitectureResult("not json")).toBeNull()
    expect(parseArchitectureResult(JSON.stringify({ style: "layered", confidence: "nope" }))).toBeNull()
  })
})

describe("PipelineRunStatus", () => {
  it("shows the run and its failure error", () => {
    render(<PipelineRunStatus execution={execution({ status: "Failed", error: "boom", result: null })} />)
    expect(screen.getByText("Failed")).toBeDefined()
    expect(screen.getByText("architect run #12")).toBeDefined()
    expect(screen.getByText("boom")).toBeDefined()
  })
})

describe("AnalyzerResultView", () => {
  it("renders verdict, language, entrypoints and components", () => {
    const summary = parseAnalyzerResult(analysis)
    if (summary === null) {
      throw new Error("analyzer fixture must parse")
    }
    render(<AnalyzerResultView summary={summary} />)
    expect(screen.getByText("Analysis")).toBeDefined()
    expect(screen.getByText("library")).toBeDefined()
    expect(screen.getByText("python")).toBeDefined()
    expect(screen.getByText("A widget library.")).toBeDefined()
    expect(screen.getByText("main.py")).toBeDefined()
    expect(screen.getByText("pkg/core.py")).toBeDefined()
    expect(screen.getByText("4 file(s) read, hypothesis confirmed")).toBeDefined()
  })
})

describe("ArchitectureResultView", () => {
  it("renders every pipeline section", () => {
    const summary = parseArchitectureResult(description)
    if (summary === null) {
      throw new Error("architecture fixture must parse")
    }
    render(<ArchitectureResultView description={summary} execution={execution()} />)
    expect(screen.getByText("Architecture")).toBeDefined()
    expect(screen.getByText("architect run #12")).toBeDefined()
    expect(screen.getByText("layered")).toBeDefined()
    expect(screen.getByText("hexagonal")).toBeDefined()
    expect(screen.getByText("Handlers skip the port.")).toBeDefined()
    expect(screen.getByText("Holds the core logic.", { exact: false })).toBeDefined()
    expect(screen.getByText("Execution starts at main and reaches core.")).toBeDefined()
    expect(screen.getByText("Third-party (1)")).toBeDefined()
    expect(screen.getByText("requests")).toBeDefined()
    expect(screen.getByText("a.py ↔ b.py")).toBeDefined()
    expect(screen.getByText("[modularity] One job per module.", { exact: false })).toBeDefined()
    expect(screen.getByText("Circular imports: a.py ↔ b.py")).toBeDefined()
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

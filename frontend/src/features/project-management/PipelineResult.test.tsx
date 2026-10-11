import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import {
  AnalyzerResultView,
  ArchitectureResultView,
  PipelineRunStatus,
} from "./PipelineResult.tsx"
import {
  parseAnalyzerResult,
  parseArchitectureResult,
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

import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { getProjectGraphArtifact } from "./projectGraphApi.ts"
import { StructuralGraph } from "./StructuralGraph.tsx"
import type { GraphifyGraph } from "./structuralGraphModel.ts"

vi.mock("./projectGraphApi.ts", () => ({ getProjectGraphArtifact: vi.fn() }))

const graph: GraphifyGraph = {
  nodes: [
    { id: "src_a", label: "a.ts", source_file: "src/a.ts", source_location: "L1" },
    { id: "src_a_classa", label: "ClassA", _callable: true, _callable_class: true, source_file: "src/a.ts", source_location: "L4" },
    { id: "src_a_runa", label: "runA", _callable: true, source_file: "src/a.ts", source_location: "L12" },
    { id: "src_b", label: "b.ts", source_file: "src/b.ts", source_location: "L1" },
    { id: "src_b_runb", label: "runB", _callable: true, source_file: "src/b.ts", source_location: "L6" },
  ],
  links: [
    { source: "src_a_classa", target: "src_a_runa", relation: "calls" },
    { source: "src_a_runa", target: "src_b_runb", relation: "calls" },
  ],
}

beforeEach(() => {
  vi.mocked(getProjectGraphArtifact).mockReset()
})

afterEach(async () => {
  await changeLanguage("en")
})

describe("structural graph", () => {
  it("loads the commit artifact and exposes the legend, filters and canvas", async () => {
    vi.mocked(getProjectGraphArtifact).mockResolvedValue(graph)
    render(<StructuralGraph projectId={2} taskId={81} commitHash={"a".repeat(40)} />)

    expect(screen.getByText("Loading graph data…")).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText("Modules")).toBeInTheDocument())
    expect(screen.getByText("Classes")).toBeInTheDocument()
    expect(screen.getByText("Functions")).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Structural graph for commit aaaaaaa" })).toBeInTheDocument()
    expect(screen.queryByRole("checkbox", { name: "Show classes" })).toBeNull()
    expect(screen.queryByRole("checkbox", { name: "Show functions" })).toBeNull()
    expect(getProjectGraphArtifact).toHaveBeenCalledWith(2, 81, expect.any(AbortSignal))
  })

  it("always shows classes and functions without losing the graph", async () => {
    vi.mocked(getProjectGraphArtifact).mockResolvedValue(graph)
    render(<StructuralGraph projectId={2} taskId={81} commitHash={"a".repeat(40)} />)
    await waitFor(() => expect(screen.getByText("Modules")).toBeInTheDocument())

    expect(screen.getByText("Classes")).toBeInTheDocument()
    expect(screen.getByText("Functions")).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Structural graph for commit aaaaaaa" })).toBeInTheDocument()
  })

  it("shows a retryable state when the artifact cannot be loaded", async () => {
    vi.mocked(getProjectGraphArtifact).mockRejectedValueOnce(new Error("boom")).mockResolvedValue(graph)
    const user = userEvent.setup()
    render(<StructuralGraph projectId={2} taskId={81} commitHash={"a".repeat(40)} />)

    await waitFor(() => expect(screen.getByText("Could not load graph data.")).toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Retry loading" }))
    await waitFor(() => expect(screen.getByText("Modules")).toBeInTheDocument())
    expect(getProjectGraphArtifact).toHaveBeenCalledTimes(2)
  })

  it("shows architectural explorer controls and allows searching nodes", async () => {
    vi.mocked(getProjectGraphArtifact).mockResolvedValue(graph)
    const user = userEvent.setup()
    render(<StructuralGraph projectId={2} taskId={81} commitHash={"a".repeat(40)} />)
    await waitFor(() => expect(screen.getByText("Modules")).toBeInTheDocument())

    expect(screen.getByRole("navigation", { name: "Navigation" })).toBeInTheDocument()
    expect(screen.getByLabelText("Grouping")).toBeInTheDocument()
    await user.type(screen.getByLabelText("Search modules, classes, or functions"), "ClassA")
    expect(await screen.findByRole("button", { name: /ClassA/ })).toBeInTheDocument()
  })
})

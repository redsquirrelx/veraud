import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ArchitectureContextCard } from "./ArchitectureContextCard.tsx"
import { changeLanguage } from "../../shared/i18n/index.ts"

const realFetch = globalThis.fetch

afterEach(async () => {
  globalThis.fetch = realFetch
  await changeLanguage("en")
})

const data = {
  knowledge: [
    {
      category: "components",
      subject: "Gateway",
      statement: "Routes requests to services.",
      related_subjects: ["Auth", "Cache"],
      certainty: "explicit",
      constraint: "required",
      reasoning: "The docs describe the gateway as the entry point.",
      section_ids: ["section-1"],
      evidence: [{ section_id: "section-1", start_line: 10, end_line: 18, quote: "The gateway routes every request." }],
    },
  ],
  knowledge_issues: [
    {
      category: "relationships",
      kind: "ambiguity",
      question: "Does the cache sit in front of Auth or behind it?",
      section_ids: ["section-2"],
      document_references: ["docs/cache.md"],
    },
  ],
  covered_categories: ["components"],
  pending_categories: ["architectural_style", "responsibilities", "relationships", "constraints", "interfaces_and_contracts", "architectural_decisions"],
  evaluated_categories: ["components"],
  coverage_assessment_status: "completed",
  consulted_documents: [
    { path: "docs/architecture.md", content_hash: "abcdefghijklmnopqrstuvwxyz0123456789", line_count: 42 },
  ],
  section_paths: { "section-1": "docs/architecture.md", "section-2": "docs/cache.md" },
  validation_errors: [
    { target: "claim", position: 2, section_ids: ["section-1"], reason: "Evidence range is not contiguous." },
  ],
  finalization_reason: "incomplete_coverage",
  execution_error: null,
}

describe("ArchitectureContextCard", () => {
  it("renders coverage in canonical order and claim details without counters", async () => {
    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data,
      },
    }} />)

    expect(screen.getByText("Architecture context")).toBeDefined()
    expect(screen.getByText("partial")).toBeDefined()
    expect(screen.getByText("Incomplete coverage")).toBeDefined()
    expect(screen.getByText("1/7 areas covered")).toBeDefined()
    expect(screen.getByRole("progressbar", { name: "Coverage" }).getAttribute("aria-valuenow")).toBe("14")

    const coverageLabels = [
      "Architectural style",
      "Components",
      "Responsibilities",
      "Relationships",
      "Constraints",
      "Interfaces and contracts",
      "Architectural decisions",
    ]
    const text = document.body.textContent ?? ""
    const indexes = coverageLabels.map((label) => text.indexOf(label))
    expect(indexes).toEqual([...indexes].sort((a, b) => a - b))
    expect(screen.getAllByText("Covered")).toHaveLength(1)
    expect(screen.getAllByText("Missing")).toHaveLength(6)
    expect(screen.getByText(/Main parts of the system/)).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: /Consulted documents/ }))
    expect(screen.getByText(/42 lines/)).toBeDefined()
    expect(screen.getByText(/abcdefghijkl…/)).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: /Gateway/ }))
    const knowledgeDialog = screen.getByRole("dialog", { name: "Gateway" })
    expect(knowledgeDialog.textContent).toContain("Gateway")
    expect(knowledgeDialog.textContent).toContain("Routes requests to services.")
    expect(knowledgeDialog.textContent).toContain("The docs describe the gateway")
    expect(knowledgeDialog.textContent).toContain("→ Auth, Cache")
    expect(document.body.textContent).toContain("docs/architecture.md")
    expect(document.body.textContent).toContain("L10–L18")
    expect(knowledgeDialog.textContent).toContain("Explicit")
    expect(knowledgeDialog.textContent).toContain("Required")

    expect(screen.getByText(/Does the cache sit in front of Auth/)).toBeDefined()
    expect(screen.getByText("Ambiguity")).toBeDefined()
    expect(screen.getByText(/Evidence range is not contiguous/)).toBeDefined()
    expect(screen.getByText(/#2/)).toBeDefined()
  })

  it("fills the coverage bar with partial areas in yellow", () => {
    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data: { ...data, covered_categories: [], evaluated_categories: ["components"] },
      },
    }} />)

    expect(screen.getByText("0/7 areas covered")).toBeDefined()
    const progress = screen.getByRole("progressbar", { name: "Coverage" })
    expect(progress.getAttribute("aria-valuenow")).toBe("14")
    const partialFill = progress.querySelector(".architecture-coverage-progress-fill.is-partial")
    expect(partialFill?.getAttribute("style")).toContain("width: 14%")
  })

  it("shows the version loading indicator in the card and hides context content", () => {
    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data,
      },
    }} versionLoading />)

    expect(screen.getByText("Loading version (branch and commit)…")).toBeDefined()
    expect(document.querySelector(".files-loading .ui-spinner")).not.toBeNull()
    expect(screen.queryByText("Gateway")).toBeNull()
    expect(screen.queryByText("Coverage")).toBeNull()
  })

  it("shows the applying indicator in the card", () => {
    render(<ArchitectureContextCard state={{ status: "idle" }} versionApplying />)

    expect(screen.getByText("Applying version")).toBeDefined()
    expect(document.querySelector(".files-loading .ui-spinner")).not.toBeNull()
  })

  it("opens category sources on card selection and closes the modal", async () => {
    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data,
      },
    }} />)

    await userEvent.click(screen.getByRole("button", { name: /Main parts of the system/ }))
    const dialog = screen.getByRole("dialog", { name: "Components" })
    expect(dialog).not.toBeNull()
    expect(dialog.textContent).toContain("docs/architecture.md")
    expect(dialog.textContent).toContain("L10–L18")
    expect(dialog.textContent).toContain("The gateway routes every request.")
    expect(document.querySelector(".architecture-coverage-modal .ui-modal-wide")).not.toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Close" }))
    expect(screen.queryByRole("dialog", { name: "Components" })).toBeNull()
  })

  it("opens an evidence in the same modal and returns to the preserved list", async () => {
    const lines = Array.from({ length: 20 }, (_, index) => `line ${index + 1}`).join("\n")
    globalThis.fetch = (async (_input: unknown, init?: RequestInit) => {
      const body = init?.body === undefined ? {} : (JSON.parse(String(init.body)) as { path?: string })
      return new Response(JSON.stringify({ path: body.path ?? "docs/architecture.md", content: lines, size: lines.length }), { status: 200 })
    }) as typeof fetch

    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data,
      },
    }} />)

    await userEvent.click(screen.getByRole("button", { name: /Main parts of the system/ }))
    await userEvent.click(screen.getByRole("button", { name: "docs/architecture.md L10–L18" }))

    const dialog = screen.getByRole("dialog", { name: "Components" })
    expect(await screen.findByText("Referenced excerpt")).toBeDefined()
    expect(dialog.textContent).toContain("The gateway routes every request.")
    expect(await screen.findByText("line 10")).toBeDefined()
    expect(screen.getByRole("button", { name: "Back" })).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Back" }))
    expect(screen.getByRole("dialog", { name: "Components" })).not.toBeNull()
    expect(screen.getByRole("button", { name: "docs/architecture.md L10–L18" })).toBeDefined()
    expect(screen.queryByText("line 10", { exact: false })).toBeNull()
  })

  it("filters knowledge items and navigates from knowledge detail to evidence viewer and back", async () => {
    const lines = Array.from({ length: 20 }, (_, index) => `line ${index + 1}`).join("\n")
    globalThis.fetch = (async (_input: unknown, init?: RequestInit) => {
      const body = init?.body === undefined ? {} : (JSON.parse(String(init.body)) as { path?: string })
      return new Response(JSON.stringify({ path: body.path ?? "docs/architecture.md", content: lines, size: lines.length }), { status: 200 })
    }) as typeof fetch

    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data,
      },
    }} />)

    await userEvent.click(screen.getByRole("tab", { name: /Relationships/ }))
    expect(screen.queryByText("Gateway")).toBeNull()
    expect(screen.getByText("No knowledge items match the current filters.")).toBeDefined()

    await userEvent.click(screen.getByRole("tab", { name: /Components/ }))
    await userEvent.click(screen.getByRole("button", { name: /Gateway/ }))
    await userEvent.click(screen.getByRole("button", { name: "docs/architecture.md L10–L18" }))
    expect(await screen.findByText("line 10")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Back" }))
    const knowledgeDialog = screen.getByRole("dialog", { name: "Gateway" })
    expect(knowledgeDialog.textContent).toContain("Gateway")
    expect(screen.getByRole("button", { name: "docs/architecture.md L10–L18" })).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Back" }))
    expect(screen.queryByRole("dialog", { name: "Gateway" })).toBeNull()
    expect(screen.getByRole("button", { name: /Gateway/ })).toBeDefined()
    expect(screen.getByRole("tab", { name: /Components/ })).not.toBeNull()
  })

  it("shows an empty evidence state for a category without sources", async () => {
    render(<ArchitectureContextCard state={{
      status: "ready",
      context: {
        projectId: 2,
        commitHash: "a".repeat(40),
        executionId: 41,
        executionStatus: "partial",
        schemaVersion: "1",
        createdAt: "2026-11-09T03:40:18.000Z",
        data,
      },
    }} />)

    await userEvent.click(screen.getByRole("button", { name: /Patterns, principles/ }))
    const dialog = screen.getByRole("dialog", { name: "Architectural style" })
    expect(dialog.textContent).toContain("No documentary evidence is available for this category yet.")
  })
})

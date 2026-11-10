import { afterEach, describe, expect, it, vi } from "vitest"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { initializeI18n } from "../../shared/i18n/index.ts"
import { listQualityAudits, type QualityAuditSummary } from "../../features/project-management/qualityAuditApi.ts"
import { ProjectAuditSummary } from "./ProjectAuditSummary.tsx"

vi.mock("../../features/project-management/qualityAuditApi.ts", () => ({ listQualityAudits: vi.fn() }))

const hash = "a".repeat(40)
const otherHash = "b".repeat(40)
const audit = (id: number, commitHash: string | null, executionStatus = "Completed") => ({
  id, commitHash, executionStatus,
}) as QualityAuditSummary

function summary(commitHash: string | null = hash, projectId = 2) {
  return <MemoryRouter><ProjectAuditSummary key={projectId} projectId={projectId} commitHash={commitHash} /></MemoryRouter>
}

function count(label: string) {
  return within(screen.getByText(label).closest("div")!).getByRole("definition")
}

afterEach(async () => {
  vi.resetAllMocks()
  vi.useRealTimers()
  await initializeI18n("en")
})

describe("ProjectAuditSummary", () => {
  it("counts audit runs across all statuses and distinguishes the selected commit from the project total", async () => {
    vi.mocked(listQualityAudits).mockResolvedValue([
      audit(1, hash), audit(2, hash, "Failed"), audit(3, otherHash), audit(4, null, "Cancelled"),
    ])
    const view = render(summary())
    await waitFor(() => expect(count("Selected version")).toHaveTextContent("2"))
    expect(count("Project total")).toHaveTextContent("4")
    expect(screen.getByRole("link", { name: "Audits" })).toHaveAttribute("href", "/projects/2/audits")
    expect(screen.getByText("aaaaaaa")).toHaveAttribute("title", hash)

    view.rerender(summary(otherHash))
    expect(count("Selected version")).toHaveTextContent("1")
    expect(count("Project total")).toHaveTextContent("4")
    expect(listQualityAudits).toHaveBeenCalledTimes(1)

    view.rerender(summary("c".repeat(40)))
    expect(count("Selected version")).toHaveTextContent("0")
  })

  it("shows zero for an empty history, but not for an unknown selection", async () => {
    vi.mocked(listQualityAudits).mockResolvedValue([])
    const view = render(summary())
    await waitFor(() => expect(count("Project total")).toHaveTextContent("0"))
    expect(count("Selected version")).toHaveTextContent("0")
    view.rerender(summary(null))
    expect(count("Selected version")).toHaveTextContent("—")
    expect(screen.queryByText("aaaaaaa")).toBeNull()
  })

  it("does not show a false zero while loading or when the request fails, and allows retry", async () => {
    let reject!: (error: Error) => void
    vi.mocked(listQualityAudits).mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
    render(summary())
    expect(screen.getByRole("region", { name: "Audits" })).toHaveAttribute("aria-busy", "true")
    expect(count("Project total")).toHaveTextContent("—")
    await act(async () => reject(new Error("private server detail")))
    expect(await screen.findByRole("alert")).not.toHaveTextContent("private server detail")
    expect(count("Project total")).toHaveTextContent("—")
    vi.mocked(listQualityAudits).mockResolvedValue([audit(1, hash)])
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    await waitFor(() => expect(count("Project total")).toHaveTextContent("1"))
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("refreshes while an audit is running and stops polling once it finishes", async () => {
    vi.useFakeTimers()
    vi.mocked(listQualityAudits).mockResolvedValueOnce([audit(1, hash, "Running")])
      .mockResolvedValue([audit(1, hash), audit(2, hash)])
    render(summary())
    await act(async () => {})
    expect(count("Project total")).toHaveTextContent("1")
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(count("Project total")).toHaveTextContent("2")
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(listQualityAudits).toHaveBeenCalledTimes(2)
  })

  it("aborts on project changes and ignores stale responses", async () => {
    let resolve!: (rows: QualityAuditSummary[]) => void
    vi.mocked(listQualityAudits).mockReturnValueOnce(new Promise((done) => { resolve = done }))
      .mockResolvedValue([audit(3, otherHash)])
    const view = render(summary())
    const signal = vi.mocked(listQualityAudits).mock.calls[0][1]
    view.rerender(summary(otherHash, 3))
    await waitFor(() => expect(count("Project total")).toHaveTextContent("1"))
    expect(signal?.aborted).toBe(true)
    await act(async () => resolve([audit(1, hash), audit(2, hash)]))
    expect(count("Project total")).toHaveTextContent("1")
  })

  it("renders concise Spanish labels", async () => {
    await initializeI18n("es")
    vi.mocked(listQualityAudits).mockResolvedValue([audit(1, hash)])
    render(summary())
    await waitFor(() => expect(count("Versión seleccionada")).toHaveTextContent("1"))
    expect(count("Total del proyecto")).toHaveTextContent("1")
    expect(screen.getByRole("link", { name: "Auditorías" })).toBeVisible()
  })
})

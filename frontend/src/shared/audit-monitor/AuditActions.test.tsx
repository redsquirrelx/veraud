import { beforeEach, expect, it, vi } from "vitest"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditStatusDisclosure } from "./AuditStatusDisclosure.tsx"
import type { AuditStatusModel } from "./auditStatus.ts"
import { changeLanguage } from "../i18n/index.ts"
import { cancelQualityAudit, type AuditCancellationResult } from "../../infrastructure/http-client/httpClient.ts"

vi.mock("../../infrastructure/http-client/httpClient.ts", async (original) => ({
  ...await original<typeof import("../../infrastructure/http-client/httpClient.ts")>(), cancelQualityAudit: vi.fn(),
}))

const requested: AuditCancellationResult = { id: 41, executionStatus: "Running", auditStatus: "cancelling",
  cancellationRequestedAt: "2026-10-30T12:00:00Z", finishedAt: null, error: null }

const audit: AuditStatusModel = {
  canCancel: true,
  id: 41, project: { id: 5, repositoryOwner: "acme", repositoryName: "Payments" },
  branch: "main", commitHash: null, state: "running", error: null,
  createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: false,
  pipelines: [{ id: "security", state: "running", agents: [] }],
}

beforeEach(async () => {
  vi.mocked(cancelQualityAudit).mockReset().mockResolvedValue(requested)
  window.localStorage.clear()
  await changeLanguage("en")
})

function show(model = audit) {
  return render(<MemoryRouter><AuditStatusDisclosure audit={model} defaultExpanded={false} /></MemoryRouter>)
}

it("keeps a single cancel action visible when execution cards are collapsed", async () => {
  show()
  const cancel = screen.getByRole("button", { name: "Cancel audit" })
  expect(cancel).toBeVisible()
  expect(cancel).toHaveClass("audit-status-project", "audit-cancel-button")
  expect(cancel.textContent).toBe("")
  const row = cancel.closest(".audit-disclosure-actions") as HTMLElement
  const repository = within(row).getByRole("link")
  expect(repository).toHaveTextContent("acme/Payments")
  expect(repository.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  await userEvent.click(screen.getByRole("button", { name: /Audit #41.*Running/ }))
  expect(screen.getAllByRole("button", { name: "Cancel audit" })).toHaveLength(1)
  expect(cancel).toBeVisible()
})

it("identifies the audit, warns about pending tasks and dismisses without changing execution", async () => {
  show()
  const cancel = screen.getByRole("button", { name: "Cancel audit" })
  await userEvent.click(cancel)
  const modal = screen.getByRole("dialog", { name: "Cancel audit?" })
  const target = within(modal).getByRole("region", { name: "Selected audit" })
  expect(within(target).getByText("Audit #41")).toBeVisible()
  expect(within(target).getByText("acme/Payments")).toBeVisible()
  expect(within(modal).getByRole("region", { name: "What happens if you cancel?" })).toBeVisible()
  expect(within(modal).getByText(/will stop its pending tasks/)).toBeVisible()
  expect(within(modal).getByRole("button", { name: "Confirm cancellation" })).toBeEnabled()
  await userEvent.click(within(modal).getByRole("button", { name: "Keep running" }))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(cancel).toHaveFocus()
  await userEvent.click(cancel)
  await userEvent.keyboard("{Escape}")
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(cancel).toHaveFocus()
})

it("keeps DEMO isolated without sending any real request", async () => {
  show({ ...audit, demo: true })
  const cancel = screen.getByRole("button", { name: "Cancel audit" })
  await userEvent.click(cancel)
  await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }))
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(cancel).toBeVisible()
  expect(cancel).toHaveFocus()
  expect(audit.state).toBe("running")
  expect(cancelQualityAudit).not.toHaveBeenCalled()
})

it("shows pending progress, blocks duplicate submissions and waits for a confirmed terminal state", async () => {
  let finish!: (value: AuditCancellationResult) => void
  vi.mocked(cancelQualityAudit).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const { rerender } = show()
  await userEvent.click(screen.getByRole("button", { name: "Cancel audit" }))
  await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }))
  const modal = screen.getByRole("dialog")
  expect(within(modal).getByRole("button", { name: "Cancelling…" })).toBeDisabled()
  await userEvent.click(within(modal).getByRole("button", { name: "Cancelling…" }))
  expect(cancelQualityAudit).toHaveBeenCalledExactlyOnceWith(5, 41)
  await act(async () => { finish(requested) })
  expect(within(modal).getByText(/Waiting for the server/)).toBeVisible()
  expect(screen.queryByText("Cancelled")).not.toBeInTheDocument()
  await userEvent.click(within(modal).getAllByRole("button", { name: "Close" })[1])
  expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled()
  rerender(<MemoryRouter><AuditStatusDisclosure audit={{ ...audit, state: "cancelled" }} /></MemoryRouter>)
  expect(screen.getByRole("button", { name: /Audit #41.*Cancelled/ })).toBeVisible()
  expect(screen.queryByRole("button", { name: "Cancelling…" })).not.toBeInTheDocument()
})

it("allows retrying after an error without claiming cancellation", async () => {
  vi.mocked(cancelQualityAudit).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(requested)
  show()
  await userEvent.click(screen.getByRole("button", { name: "Cancel audit" }))
  await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }))
  expect(await screen.findByRole("alert")).toHaveTextContent(/You can retry/)
  await userEvent.click(screen.getByRole("button", { name: "Retry cancellation" }))
  await waitFor(() => expect(cancelQualityAudit).toHaveBeenCalledTimes(2))
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})

it("restores a server-requested cancellation without offering another request", () => {
  show({ ...audit, state: "cancelling" })
  expect(screen.getByRole("button", { name: "Cancelling…" })).toBeDisabled()
  expect(cancelQualityAudit).not.toHaveBeenCalled()
})

it("never offers cancellation for analysis-only or unidentified executions", () => {
  show({ ...audit, canCancel: false })
  expect(screen.queryByRole("button", { name: "Cancel audit" })).not.toBeInTheDocument()
})

it.each(["completed", "failed"] as const)("does not offer cancellation for %s audits", (state) => {
  show({ ...audit, state })
  expect(screen.queryByRole("button", { name: "Cancel audit" })).not.toBeInTheDocument()
})

it("closes confirmation if the audit finishes while it is open", async () => {
  const { rerender } = show()
  await userEvent.click(screen.getByRole("button", { name: "Cancel audit" }))
  rerender(<MemoryRouter><AuditStatusDisclosure audit={{ ...audit, state: "completed" }} /></MemoryRouter>)
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Cancel audit" })).not.toBeInTheDocument()
})

it("shows the confirmation in Spanish", async () => {
  await changeLanguage("es")
  show()
  await userEvent.click(screen.getByRole("button", { name: "Cancelar auditoría" }))
  expect(screen.getByRole("dialog", { name: "¿Cancelar auditoría?" })).toBeVisible()
  expect(screen.getByText(/se detendrán sus tareas pendientes/)).toBeVisible()
  await changeLanguage("en")
})

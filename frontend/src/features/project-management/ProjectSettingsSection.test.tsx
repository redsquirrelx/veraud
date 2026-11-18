import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { I18nextProvider } from "react-i18next"
import { ToastProvider } from "../../app/toasts.tsx"
import { i18n, initializeI18n } from "../../shared/i18n/index.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import { ProjectSettingsSection } from "./ProjectSettingsSection.tsx"

const realFetch = globalThis.fetch

const project: ProjectSummary = {
  id: 5,
  repositoryOwner: "acme",
  repositoryName: "demo",
  cloneProtocol: "https",
  status: "READY",
  registeredAt: new Date().toISOString(),
  lastSyncedAt: null,
  branch: "main",
  commitHash: "a".repeat(40),
}

beforeAll(async () => {
  await initializeI18n("en")
})

afterEach(async () => {
  globalThis.fetch = realFetch
  await initializeI18n("en")
})

function stubDelete(outcome: { status: number, body?: unknown }) {
  const calls: Array<{ url: string, method: string }> = []
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith("/api/projects/5") && init?.method === "DELETE") {
      calls.push({ url, method: "DELETE" })
      return new Response(JSON.stringify(outcome.body ?? {}), { status: outcome.status, headers: { "content-type": "application/json" } })
    }
    throw new Error(`Unexpected fetch: ${url} ${init?.method}`)
  }) as unknown as typeof fetch
  return calls
}

function renderPage() {
  return render(
    <I18nextProvider i18n={i18n}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/projects/5/project-settings"]}>
          <Routes>
            <Route path="/projects/5/project-settings" element={<ProjectSettingsSection project={project} />} />
            <Route path="/" element={<p data-testid="home">Home</p>} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </I18nextProvider>,
  )
}

describe("ProjectSettingsSection", () => {
  it("shows the danger zone with the exact repository slug and asks for it before deleting", async () => {
    const calls = stubDelete({ status: 200, body: { status: "deleted", counts: { versions: 1, evaluations: 1, executions: 2, events: 3, architectureArtifacts: 1, tasks: 1, graphExtractions: 1 }, disk: { artifactsRemoved: [], artifactsSkipped: 0, artifactFailures: [], cloneRemoved: true, cloneFailure: null } } })
    const user = userEvent.setup()
    renderPage()
    expect(screen.getByRole("heading", { name: "Project Settings" })).toBeTruthy()
    expect(screen.getByRole("heading", { name: "Danger zone" })).toBeTruthy()
    await user.click(screen.getByRole("button", { name: "Delete project" }))
    const confirm = screen.getByRole("button", { name: "Delete permanently" })
    expect(confirm).toHaveProperty("disabled", true)
    await user.type(screen.getByLabelText("Type acme/demo to confirm"), "acme/wrong")
    expect(confirm).toHaveProperty("disabled", true)
    await user.clear(screen.getByLabelText("Type acme/demo to confirm"))
    await user.type(screen.getByLabelText("Type acme/demo to confirm"), "acme/demo")
    expect(confirm).toHaveProperty("disabled", false)
    await user.click(confirm)
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]?.method).toBe("DELETE")
    await waitFor(() => expect(screen.getByTestId("home")).toBeTruthy())
  })

  it("keeps the user on the section when executions are still cancelling and allows a retry", async () => {
    const calls = stubDelete({ status: 202, body: { status: "cancelling", message: "Open executions were asked to cancel; retry in a few seconds", pendingExecutionIds: [41] } })
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole("button", { name: "Delete project" }))
    await user.type(screen.getByLabelText("Type acme/demo to confirm"), "acme/demo")
    await user.click(screen.getByRole("button", { name: "Delete permanently" }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(screen.getByRole("status").textContent ?? "").toContain("still running")
    expect(screen.queryByTestId("home")).toBeNull()
  })

  it("surfaces a backend refusal such as in-flight git operations", async () => {
    const calls = stubDelete({ status: 422, body: { message: "The project has 1 ongoing operation; wait for them to finish" } })
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole("button", { name: "Delete project" }))
    await user.type(screen.getByLabelText("Type acme/demo to confirm"), "acme/demo")
    await user.click(screen.getByRole("button", { name: "Delete permanently" }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(screen.getByRole("alert").textContent ?? "").toContain("ongoing operation")
  })
})

import { afterEach, expect, it, vi } from "vitest"
import { StrictMode } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AuditEvidenceBrowser } from "./AuditEvidenceBrowser.tsx"
import { evidenceFilePath, readAgentEvidence } from "./auditAgentEvidence.ts"

const evidence = readAgentEvidence({ evidence_inventory: [{ id: "E-1", kind: "source", source: "Demo/src/service.ts",
  start_line: 2, end_line: 3, content: "Recorded excerpt", commit: "audited-commit",
  provenance: { agent_id: "responsibility", invocation_id: "inv-1" } }] }, "inv-1")!.evidence
const fullContent = "import { repository } from './repository'\nexport function findProject() {\n  return repository.findAll()\n}\n// end of full file"
const fileResponse = (path = "src/service.ts", content = fullContent) => new Response(JSON.stringify({ path, content, size: content.length }), { status: 200 })
afterEach(() => vi.restoreAllMocks())

it("automatically loads the selected complete file through the Files endpoint and marks evidence lines", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(fileResponse())
  render(<AuditEvidenceBrowser evidence={evidence} projectId={2} repositoryName="Demo" />)
  const viewer = screen.getByRole("region", { name: "Read-only code viewer" })
  await waitFor(() => expect(viewer).toHaveTextContent("end of full file"))
  expect(fetch.mock.calls[0][0]).toContain("/api/projects/2/file")
  expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ path: "src/service.ts" }) })
  expect(viewer).toHaveTextContent("current working copy")
  expect(Array.from(viewer.querySelectorAll(".ui-code-number"), (item) => item.textContent)).toEqual(["1", "2", "3", "4", "5"])
  expect(Array.from(viewer.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["2", "3"])
  expect(screen.queryByRole("button", { name: "Use recorded evidence" })).toBeNull()
  expect(fetch).toHaveBeenCalledTimes(1)
})

it("keeps recorded evidence and allows retrying when the checkout file cannot be read", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ message: "File was removed" }), { status: 422 }))
    .mockResolvedValueOnce(fileResponse())
  render(<AuditEvidenceBrowser evidence={evidence} projectId={2} repositoryName="Demo" />)
  expect(await screen.findByRole("alert")).toHaveTextContent("File was removed")
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("Recorded excerpt")
  await userEvent.click(screen.getByRole("button", { name: "Retry file loading" }))
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull())
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("end of full file")
  expect(fetch).toHaveBeenCalledTimes(2)
})

it("does not display a late file response after selecting a different evidence source", async () => {
  let release!: (response: Response) => void
  vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
    .mockResolvedValueOnce(fileResponse("src/other.ts", "Second complete source"))
  render(<AuditEvidenceBrowser evidence={[...evidence, { ...evidence[0], id: "E-2", source: "src/other.ts", content: "Second recorded source" }]} projectId={2} repositoryName="Demo" />)
  expect(await screen.findByText("Loading project file…")).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: /^E-2/ }))
  release(fileResponse())
  await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("Second complete source"))
  expect(screen.getByRole("region", { name: "Read-only code viewer" })).not.toHaveTextContent("end of full file")
})

it("reuses a loaded file when another evidence points to the same source and updates the marked range", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(fileResponse())
  render(<AuditEvidenceBrowser evidence={[...evidence, { ...evidence[0], id: "E-2", source: "src/service.ts", startLine: 4, endLine: 4 }]} projectId={2} repositoryName="Demo" />)
  await screen.findByText("Refresh file")
  await userEvent.click(screen.getByRole("button", { name: /^E-2/ }))
  expect(Array.from(document.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["4"])
  expect(fetch).toHaveBeenCalledTimes(1)
})

it("does not duplicate an in-flight read when selecting another evidence for the same path", async () => {
  let release!: (response: Response) => void
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
  render(<AuditEvidenceBrowser evidence={[...evidence, { ...evidence[0], id: "E-2", startLine: 4, endLine: 4 }]} projectId={2} repositoryName="Demo" />)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  await userEvent.click(screen.getByRole("button", { name: /^E-2/ }))
  expect(fetch).toHaveBeenCalledTimes(1)
  release(fileResponse())
  await screen.findByText("Refresh file")
  expect(Array.from(document.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["4"])
  expect(fetch).toHaveBeenCalledTimes(1)
})

it("retains the viewport frame while loading and smoothly replaces its content", async () => {
  let release!: (response: Response) => void
  vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise((resolve) => { release = resolve }))
  const { container } = render(<AuditEvidenceBrowser evidence={evidence} projectId={2} repositoryName="Demo" />)
  const frame = container.querySelector(".audit-evidence-code-frame")!
  await screen.findByText("Loading project file…")
  expect(frame).toHaveAttribute("aria-busy", "true")
  release(fileResponse())
  await screen.findByText("Refresh file")
  expect(container.querySelector(".audit-evidence-code-frame")).toBe(frame)
  expect(frame).toHaveAttribute("aria-busy", "false")
  expect(frame.querySelector(".audit-evidence-code-layer")).not.toBeNull()
})

it("does not reread the selected file on evidence polling updates or StrictMode effects", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(fileResponse())
  const { rerender } = render(<StrictMode><AuditEvidenceBrowser evidence={evidence} projectId={2} repositoryName="Demo" /></StrictMode>)
  await screen.findByText("Refresh file")
  rerender(<StrictMode><AuditEvidenceBrowser evidence={evidence.map((item) => ({ ...item }))} projectId={2} repositoryName="Demo" /></StrictMode>)
  expect(fetch).toHaveBeenCalledTimes(1)
})

it("does not attempt repository access for URI or absolute evidence sources", () => {
  const fetch = vi.spyOn(globalThis, "fetch")
  render(<AuditEvidenceBrowser evidence={[{ ...evidence[0], source: "https://scanner/result" }]} projectId={2} />)
  expect(screen.queryByRole("button", { name: "Load complete file" })).toBeNull()
  expect(screen.getByText(/does not specify a valid repository-relative/)).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})

it.each(["../secret", "/absolute/file.ts", "C:\\workspace\\file.ts", "https://scanner/result", ".git/config", "src//file.ts", "src/./file.ts"])("does not turn an invalid source into a file request: %s", (source) => {
  expect(evidenceFilePath(source)).toBeNull()
})

it("normalizes repository-prefixed relative paths like the Files section", () => {
  expect(evidenceFilePath("Demo\\src\\service.ts", "Demo")).toBe("src/service.ts")
  expect(evidenceFilePath("src/service.ts", "Demo")).toBe("src/service.ts")
})

import { beforeEach, afterEach, expect, it, vi } from "vitest"
import { cleanup, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { VerificationWorkspace } from "./VerificationWorkspace.tsx"
import type { VerificationSuitePage } from "./qualityAuditApi.ts"
import { useAuditSourceFile } from "./useAuditSourceFile.ts"

vi.mock("./useAuditSourceFile.ts", () => ({ useAuditSourceFile: vi.fn() }))
const emptyPage = { commits: [], hasMore: false, baselineCommit: "b".repeat(40), branch: "main", branchTip: "b".repeat(40), limit: 30, offset: 0 }
beforeEach(async () => {
  await changeLanguage("en")
  vi.mocked(useAuditSourceFile).mockReturnValue({ file: null, loading: false, failed: true, retry: vi.fn() })
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(emptyPage), { status: 200 })))
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })

const suite: VerificationSuitePage = { action: "create", ok: true, run_id: "audit-1", termination_reason: "suite_packaged",
  zip_path: "suite.zip", validation_status: "generated", limitations: [], verifications: [] }
const execution: VerificationSuitePage = { ...suite, action: "execute", validation_status: "partial", verifications: [
  { verification_id: "v1", covered_property: "No destructive calls", rule_id: "forbidden_call", strategy: "static_ast", status: "VIOLATION_PRESENT", generated_by: "llm", summary: "AssertionError: C:/private/repo/file.py {'internal': [1, 2]}", target_components: ["src/report.py"] },
  { verification_id: "v2", covered_property: "Public boundary", rule_id: "layer_import", strategy: "static_ast", status: "VERIFIED_FIXED" },
  { verification_id: "v3", covered_property: "Runtime check", rule_id: null, strategy: "dynamic_mock", status: "EXECUTION_ERROR" },
  { verification_id: "v4", covered_property: "Uncollected check", rule_id: null, strategy: "static_ast", status: "NOT_VERIFIABLE" },
] }

function show(result: VerificationSuitePage | null = execution, available = true) {
  const handlers = { create: vi.fn(), execute: vi.fn(), download: vi.fn() }
  const onTargetChange = vi.fn()
  const onSuiteScopeChange = vi.fn()
  render(<VerificationWorkspace projectId={1} auditId={2} baseline={"b".repeat(40)} suite={suite} execution={result}
    branch="main" targetCommit={"c".repeat(40)} onTargetChange={onTargetChange}
    suiteScope="all" onSuiteScopeChange={onSuiteScopeChange}
    available={available} enabled busy={false} action={null} downloading={false} error={null} reconnecting={false} {...handlers} />)
  return { ...handlers, onTargetChange, onSuiteScopeChange }
}

it("keeps the descendant commit list visible and selecting one targets execution", async () => {
  const page = {
    commits: [
      { commitHash: "d".repeat(40), subject: "Fix one" },
      { commitHash: "a".repeat(40), subject: "Baseline" },
    ],
    hasMore: true, baselineCommit: "a".repeat(40), branch: "main", branchTip: "d".repeat(40), limit: 30, offset: 0,
  }
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(page), { status: 200 }))
  vi.stubGlobal("fetch", fetchMock)
  const handlers = show(null)
  expect(await screen.findByRole("button", { name: "Select a target commit" })).toBeVisible()
  expect(fetchMock).toHaveBeenCalledOnce()
  expect(fetchMock.mock.calls[0][0]).toContain("/api/projects/1/audits/2/verification-commits")
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Select a target commit" }))
  await user.click(screen.getByRole("option", { name: new RegExp(`^${"d".repeat(10)}`) }))
  expect(handlers.onTargetChange).toHaveBeenCalledWith("d".repeat(40))
  expect(handlers.create).not.toHaveBeenCalled()
  expect(handlers.execute).not.toHaveBeenCalled()
})

it("shows no execution metrics for a created-only suite and keeps the actions separate", async () => {
  const handlers = show(null)
  expect(screen.getByText(/No execution results are available yet/)).toBeVisible()
  expect(screen.queryByRole("tab", { name: /Total/ })).not.toBeInTheDocument()
  const user = userEvent.setup()
  await user.click(screen.getByRole("button", { name: "Run verification suite" }))
  expect(handlers.execute).toHaveBeenCalledOnce()
  expect(handlers.create).not.toHaveBeenCalled()
  await user.click(screen.getByRole("button", { name: "Download suite" }))
  expect(handlers.download).toHaveBeenCalledOnce()
  expect(screen.getByText("b".repeat(40))).toBeVisible()
  expect(screen.getByText(/temporary copy of the selected commit/)).toBeVisible()
})

it("counts real outcomes separately and exposes full diagnostics only in expanded detail", async () => {
  show()
  expect(screen.getByRole("tab", { name: "Total (4)" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "Error (1)" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "Other / no verdict (1)" })).toBeVisible()
  const message = screen.getByText(execution.verifications[0].summary!)
  expect(message).not.toBeVisible()
  const user = userEvent.setup()
  const row = screen.getByText("v1").closest("details")!
  await user.click(row.querySelector("summary")!)
  expect(within(row).getByText("forbidden_call")).toBeVisible()
  await user.click(within(row).getByText("View full message"))
  expect(message).toBeVisible()
  await user.click(screen.getByRole("tab", { name: "Passed (1)" }))
  expect(screen.queryByText("v1")).not.toBeInTheDocument()
  expect(screen.getByText("v2")).toBeVisible()
  expect(screen.getByText(/does not by itself confirm a fix/)).toBeVisible()
})

it("opens only supplied relative file references through the existing baseline source reader", async () => {
  show()
  const user = userEvent.setup()
  await user.click(screen.getByText("v1").closest("details")!.querySelector("summary")!)
  await user.click(screen.getByRole("button", { name: "src/report.py" }))
  expect(useAuditSourceFile).toHaveBeenCalledWith(1, 2, "src/report.py", "b".repeat(40))
  expect(screen.getByText(/not evidence of the executed checkout/)).toBeVisible()
})

it("keeps running disabled without an available artifact", () => {
  show(null, false)
  expect(screen.getByRole("button", { name: "Run verification suite" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "Download suite" })).toBeDisabled()
})

it("exposes dynamic group scope tabs from the unified suite and forwards scope changes", async () => {
  const groupedSuite: VerificationSuitePage = { ...suite, groups: [{ name: "modularity", count: 2 }, { name: "testability", count: 2 }], verifications: [
    { verification_id: "m1", covered_property: "p", rule_id: "r", strategy: "static_ast", status: "VIOLATION_PRESENT", group: "modularity", generator: "finding_test_generation" },
    { verification_id: "t1", covered_property: "p", rule_id: null, strategy: "static_ast", status: "VERIFIED_FIXED", group: "testability", generator: "testability_probe" },
  ] }
  const handlers = { create: vi.fn(), execute: vi.fn(), download: vi.fn() }
  const onSuiteScopeChange = vi.fn()
  render(<VerificationWorkspace projectId={1} auditId={2} baseline={"b".repeat(40)} suite={groupedSuite} execution={null}
    branch="main" targetCommit={"c".repeat(40)} onTargetChange={vi.fn()}
    suiteScope="all" onSuiteScopeChange={onSuiteScopeChange}
    available={true} enabled busy={false} action={null} downloading={false} error={null} reconnecting={false} {...handlers} />)
  const user = userEvent.setup()
  expect(screen.getByRole("tab", { name: /All/ })).toBeVisible()
  expect(screen.getByRole("tab", { name: "modularity (2)" })).toBeVisible()
  expect(screen.getByRole("tab", { name: "testability (2)" })).toBeVisible()
  await user.click(screen.getByRole("tab", { name: "testability (2)" }))
  expect(onSuiteScopeChange).toHaveBeenCalledTimes(1)
  expect(onSuiteScopeChange).toHaveBeenCalledWith("testability")
})

it("renders a group badge per row in the results table", () => {
  const groupedExecution: VerificationSuitePage = { ...suite, action: "execute", validation_status: "partial", verifications: [
    { verification_id: "t1", covered_property: "p", rule_id: null, strategy: "static_ast", status: "VIOLATION_PRESENT", group: "testability", generator: "testability_probe" },
  ] }
  show(groupedExecution)
  expect(screen.getByText("testability")).toBeVisible()
})
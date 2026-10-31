import { beforeEach, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage } from "../i18n/index.ts"
import { AuditStatusView } from "./AuditStatusView.tsx"
import { demoAudit } from "./demoAudit.ts"
import { AuditStatusDisclosure } from "./AuditStatusDisclosure.tsx"

beforeEach(async () => {
  window.localStorage.clear()
  await changeLanguage("es")
})

it("indicates audit and agent errors and reveals each message only on demand", async () => {
  const user = userEvent.setup()
  render(<MemoryRouter><AuditStatusView audit={demoAudit} /></MemoryRouter>)
  expect(screen.getAllByText("Fallida").some((label) => label.closest(".ui-badge-danger"))).toBe(true)
  expect(screen.getAllByRole("img", { name: "Error de ejecución" }).length).toBeGreaterThanOrEqual(2)
  expect(screen.queryByText(demoAudit.error!)).not.toBeInTheDocument()
  const trigger = screen.getByRole("button", { name: /Ver error/ })
  await user.click(trigger)
  expect(screen.getByRole("dialog", { name: "Error de ejecución" })).toBeVisible()
  expect(screen.getByText(demoAudit.error!)).toBeVisible()
  await user.keyboard("{Escape}")
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  await user.click(screen.getByRole("button", { name: /Detalles de ejecución ·/ }))
  expect(screen.queryByText(demoAudit.pipelines[0].agents[0].error!)).not.toBeInTheDocument()
  const controls = screen.getAllByRole("button", { name: /Ver error/ })
  await user.click(controls[1])
  expect(screen.getByText(demoAudit.pipelines[0].agents[0].error!)).toBeVisible()
  expect(screen.queryByText(demoAudit.error!)).not.toBeInTheDocument()
})

it("does not offer error controls without a recorded message", () => {
  render(<MemoryRouter><AuditStatusView audit={{ ...demoAudit, error: null, pipelines: [] }} /></MemoryRouter>)
  expect(screen.queryByText("Ver error")).not.toBeInTheDocument()
  expect(screen.getByRole("img", { name: "Error de ejecución" })).toBeVisible()
})

it("propagates a message-less child failure through collapsed ancestors without changing their states", async () => {
  const base = demoAudit.pipelines[0].agents[0]
  const audit = { ...demoAudit, state: "partial" as const, error: null, pipelines: [{
    id: "security", state: "partial" as const, agents: [
      { ...base, id: "root", agentType: "security", state: "completed" as const, error: null },
      { ...base, id: "parent", parentId: "root", agentType: "coordinator", state: "completed" as const, error: null },
      { ...base, id: "child", parentId: "parent", agentType: "investigator", state: "failed" as const, error: null },
    ],
  }] }
  render(<MemoryRouter><AuditStatusDisclosure audit={audit} defaultExpanded={false} /></MemoryRouter>)
  const auditToggle = screen.getByRole("button", { name: /Auditoría #-2/ })
  expect(within(auditToggle).getByRole("img", { name: "Error de ejecución" })).toBeVisible()
  await userEvent.click(auditToggle)
  for (const id of ["root", "parent", "child"]) {
    const toggle = screen.getByRole("button", { name: new RegExp(`^Ejecución de .* #${id}$`) })
    expect(within(toggle).getByRole("img", { name: "Error de ejecución" })).toBeVisible()
  }
  expect(screen.queryByRole("button", { name: /Ver error/ })).not.toBeInTheDocument()
  const root = screen.getByRole("button", { name: "Ejecución de security #root" })
  expect(root.closest("li")).toHaveAttribute("data-state", "completed")
  await userEvent.click(root)
  expect(within(root).getByRole("img", { name: "Error de ejecución" })).toBeVisible()
  await userEvent.click(auditToggle)
  expect(within(auditToggle).getByRole("img", { name: "Error de ejecución" })).toBeVisible()
})

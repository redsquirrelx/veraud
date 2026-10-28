import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { AuditAttributeSummary } from "./AuditAttributeSummary.tsx"
import type { AuditAgentCatalog } from "./auditAgentCatalog.ts"

afterEach(async () => { cleanup(); await changeLanguage("en") })

function agent(agentType: string, values: Partial<AgentSettings> = {}): AgentSettings {
  return { agentType, name: agentType, qualityAttributes: ["maintainability"], workflowIds: [],
    configured: false, configuration: null, availability: "available", ...values }
}

const agents = [
  agent("modularity", { childAgentTypes: ["architecture_boundary", "responsibility"] }),
  agent("reusability", { childAgentTypes: ["abstraction"] }),
  agent("architecture_boundary", { role: "investigator" }), agent("responsibility", { role: "investigator" }),
  agent("abstraction", { role: "investigator" }),
  agent("security", { childAgentTypes: ["secret_scanner", "dast_sandbox", "new_scanner"] }),
  agent("secret_scanner"), agent("dast_sandbox", { availability: "not_executed" }), agent("new_scanner", { name: "New Scanner" }),
]
const catalog: AuditAgentCatalog = { agents, loading: false, failed: false, retry: vi.fn() }

describe("audit attribute summary", () => {
  it("groups active investigators under their subcharacteristic titles without descriptions or controls", () => {
    render(<AuditAttributeSummary attribute="maintainability" catalog={catalog} />)
    expect(screen.getByRole("heading", { name: "Modularity" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Reusability" })).toBeInTheDocument()
    for (const name of ["Architectural boundaries", "Responsibilities", "Abstractions"]) expect(screen.getByText(name)).toBeInTheDocument()
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
  })

  it("reflects the selected scope and translates its titles", async () => {
    render(<AuditAttributeSummary attribute="maintainability" catalog={catalog} selection={{ modularity: ["responsibility"] }} />)
    expect(screen.getByText("Responsibilities")).toBeInTheDocument()
    expect(screen.queryByText("Architectural boundaries")).not.toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Reusability" })).not.toBeInTheDocument()
    await changeLanguage("es")
    expect(screen.getByRole("heading", { name: "Modularidad" })).toBeInTheDocument()
    expect(screen.getByText("Responsabilidades")).toBeInTheDocument()
  })

  it("uses registered child names, excluding unavailable components", () => {
    render(<AuditAttributeSummary attribute="security" catalog={catalog} />)
    expect(screen.getByText("Secrets")).toBeInTheDocument()
    expect(screen.getByText("New Scanner")).toBeInTheDocument()
    expect(screen.queryByText("dast_sandbox")).not.toBeInTheDocument()
  })

  it("does not invent a summary while loading or on failure and offers retry", async () => {
    const retry = vi.fn()
    const { rerender } = render(<AuditAttributeSummary attribute="security" catalog={{ ...catalog, loading: true }} />)
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument()
    expect(screen.queryByText("Secrets")).not.toBeInTheDocument()
    rerender(<AuditAttributeSummary attribute="security" catalog={{ ...catalog, failed: true, retry }} />)
    expect(screen.getByText("Summary unavailable")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(retry).toHaveBeenCalledOnce()
  })
})

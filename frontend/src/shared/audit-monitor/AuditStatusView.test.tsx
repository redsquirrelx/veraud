import { afterEach, describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditStatusView } from "./AuditStatusView.tsx"
import { changeLanguage } from "../i18n/index.ts"
import type { AuditStatusModel } from "./auditStatus.ts"

const audit: AuditStatusModel = {
  id: 41,
  project: { id: 5, repositoryOwner: "acme", repositoryName: "Payments" },
  branch: "main",
  commitHash: "9f2c1ab7de4d0c6b5a8391f4e2d7c8b0a6e5f4d3",
  state: "running",
  error: null,
  createdAt: "2026-10-17T10:00:00Z",
  finishedAt: null,
  reportAvailable: false,
  pipelines: [
    {
      id: "maintainability",
      state: "running",
      agents: [
        {
          id: 118, agentType: "maintainability_manager", state: "completed",
          inputTokens: 41230, outputTokens: 9840,
          startedAt: "2026-10-17T10:00:12Z", finishedAt: "2026-10-17T10:04:41Z", error: null,
        },
        {
          id: 120, agentType: "maintainability_judge", state: "waiting",
          inputTokens: null, outputTokens: null,
          startedAt: null, finishedAt: null, error: null,
        },
      ],
    },
    { id: "security", state: "running", agents: [] },
  ],
}

/** Query a region of the view so repeated chrome ("Failed", timestamps) stays unambiguous. */
function part(root: HTMLElement, selector: string): HTMLElement {
  const found = root.querySelector<HTMLElement>(selector)
  if (found === null) {
    throw new Error(`Missing ${selector}`)
  }
  return found
}

function byId(id: string | null): HTMLElement {
  const found = id === null ? null : document.getElementById(id)
  if (found === null) {
    throw new Error(`Missing element #${id}`)
  }
  return found
}

function show(model: AuditStatusModel = audit) {
  render(
    <MemoryRouter>
      <AuditStatusView audit={model} />
    </MemoryRouter>,
  )
  return screen.getByRole("group")
}

describe("AuditStatusView", () => {
  it("exposes a labelled region and shows the audit identity", () => {
    const region = show()

    expect(screen.getByRole("group", { name: "Audit status" })).toBeInTheDocument()
    expect(region).toBeInTheDocument()
    expect(within(region).getByText("Audit #41")).toBeInTheDocument()
    expect(within(region).getByText("main @ 9f2c1ab")).toBeInTheDocument()
    expect(within(part(region, ".audit-status-head")).getByText("Running")).toBeInTheDocument()
  })

  it("links the audited project to its audits section", () => {
    const region = show()

    const link = within(part(region, ".audit-status-meta")).getByRole("link", { name: "Open acme/Payments" })

    expect(link).toHaveAttribute("href", "/projects/5/audits")
    expect(within(link).getByText("acme/Payments")).toBeInTheDocument()
  })

  it("keeps the project link on its own repository for another audit", () => {
    const region = show({
      ...audit,
      project: { id: 12, repositoryOwner: "acme", repositoryName: "Ledger" },
    })

    const link = within(part(region, ".audit-status-meta")).getByRole("link", { name: "Open acme/Ledger" })

    expect(link).toHaveAttribute("href", "/projects/12/audits")
  })

  it("sums agent progress across every pipeline in the header", () => {
    const region = show()

    // One finished and one queued agent in maintainability; security has none.
    expect(within(part(region, ".audit-status-head")).getByText("1 of 2 agents")).toBeInTheDocument()
    expect(within(part(region, ".audit-pipeline-head")).getByText("1 of 2 agents")).toBeInTheDocument()
  })

  it("names known quality attributes", () => {
    expect(within(part(show(), ".audit-pipeline-head")).getByText("Maintainability")).toBeInTheDocument()
  })

  it("falls back to the raw identifier for an unknown quality attribute", () => {
    const region = show({ ...audit, pipelines: [{ id: "performance", state: "running", agents: [] }] })

    expect(within(part(region, ".audit-pipeline-head")).getByText("performance")).toBeInTheDocument()
  })

  it("keeps the header when a pipeline has no agents", () => {
    const region = show({ ...audit, pipelines: [{ id: "security", state: "running", agents: [] }] })

    expect(within(region).getByText("No agents recorded")).toBeInTheDocument()
    expect(within(part(region, ".audit-pipeline-head")).getByText("Security")).toBeInTheDocument()
    expect(within(part(region, ".audit-status-head")).getByText("No agents yet")).toBeInTheDocument()
    expect(within(part(region, ".audit-pipeline-head")).getByText("No agents yet")).toBeInTheDocument()
  })

  it("shows tokens, timestamps and the agent identifier verbatim", () => {
    const agent = part(show(), ".audit-agent")

    expect(within(agent).getByText("maintainability_manager run #118")).toBeInTheDocument()
    expect(within(agent).getByText("41,230 in · 9,840 out")).toBeInTheDocument()
    expect(within(agent).getByText(/^Started /)).toBeInTheDocument()
    expect(within(agent).getByText(/^Finished /)).toBeInTheDocument()
  })

  it("marks missing token usage instead of showing zeroes", () => {
    const region = show()

    // Only the queued agent lacks token usage.
    expect(within(part(region, ".audit-agent-list")).getByText("Token usage not reported")).toBeInTheDocument()
  })

  it("surfaces audit and agent errors as alerts at their own level", () => {
    const region = show({
      ...audit,
      state: "failed",
      error: "The security pipeline could not be started.",
      pipelines: [{
        id: "security",
        state: "failed",
        agents: [{
          id: 121, agentType: "security_scanner", state: "failed",
          inputTokens: null, outputTokens: null,
          startedAt: null, finishedAt: null,
          error: "Model-call limit reached.",
        }],
      }],
    })

    expect(within(region).getByText("The security pipeline could not be started.")).toBeInTheDocument()
    expect(within(region).getByText("Model-call limit reached.")).toBeInTheDocument()
    expect(screen.getAllByRole("alert")).toHaveLength(2)
    expect(within(part(region, ".audit-status-head")).getByText("Failed")).toBeInTheDocument()
    expect(within(part(region, ".audit-pipeline-head")).getByText("Failed")).toBeInTheDocument()
    expect(within(part(region, ".audit-agent-head")).getByText("Failed")).toBeInTheDocument()
  })

  it("falls back to a readable revision when the audit has none", () => {
    const region = show({ ...audit, branch: null, commitHash: null })

    expect(within(region).getByText("No revision recorded")).toBeInTheDocument()
    expect(within(region).queryByText(/@/)).toBeNull()
  })

  it("flags an available report and the finished timestamp", () => {
    const region = show({ ...audit, state: "completed", reportAvailable: true, finishedAt: "2026-10-17T10:20:00Z" })

    expect(within(part(region, ".audit-status-head")).getByText("Completed")).toBeInTheDocument()
    expect(within(region).getByText("Report available")).toBeInTheDocument()
    expect(within(part(region, ".audit-status-meta")).getByText(/^Finished /)).toBeInTheDocument()
  })

  it("distinguishes a partial audit from a completed one at the header", () => {
    const head = part(show({ ...audit, state: "partial" }), ".audit-status-head")

    expect(within(head).getByText("Partial")).toBeInTheDocument()
    expect(within(head).queryByText("Completed")).toBeNull()
  })
})

describe("AuditStatusView pipeline folding", () => {
  it("opens every pipeline by default and names each toggle from its contents", () => {
    const region = show()
    const toggles = region.querySelectorAll(".audit-pipeline-head")

    expect(toggles).toHaveLength(2)
    expect(toggles[0]).toHaveAttribute("aria-expanded", "true")
    expect(toggles[1]).toHaveAttribute("aria-expanded", "true")
    // The accessible name carries attribute, state and progress, separated.
    expect(toggles[0]).toHaveAccessibleName("Maintainability · Running · 1 of 2 agents")
    expect(toggles[1]).toHaveAccessibleName("Security · Running · No agents yet")
  })

  it("splits a pipeline across two rows: identity, then state", () => {
    const head = part(show(), ".audit-pipeline-head")
    const lines = head.querySelectorAll(".audit-pipeline-line")

    expect(lines).toHaveLength(2)
    expect(within(lines[0] as HTMLElement).getByText("Maintainability")).toBeInTheDocument()
    expect(within(lines[1] as HTMLElement).getByText("Running")).toBeInTheDocument()
    expect(within(lines[1] as HTMLElement).getByText("1 of 2 agents")).toBeInTheDocument()
    // The chevron stays on the identity row, pinned to its end.
    expect(lines[0]?.querySelector(".audit-pipeline-chevron")).not.toBeNull()
  })

  it("keeps the chevron reachable whatever the attribute name length", () => {
    const region = show({
      ...audit,
      pipelines: [{
        id: "operational-security-and-resilience-under-load",
        state: "running",
        agents: [],
      }],
    })

    const lines = part(region, ".audit-pipeline-head").querySelectorAll(".audit-pipeline-line")

    // Long name truncates inside its own row; the other row is untouched.
    expect(within(lines[0] as HTMLElement).getByText("operational-security-and-resilience-under-load")).toBeInTheDocument()
    expect(lines[0]?.querySelector(".audit-pipeline-chevron")).not.toBeNull()
    expect(within(lines[1] as HTMLElement).getByText("Running")).toBeInTheDocument()
    expect(within(lines[1] as HTMLElement).getByText("No agents yet")).toBeInTheDocument()
  })

  it("wires each toggle to the region it controls", () => {
    const region = show()
    const toggle = part(region, ".audit-pipeline-head")
    const controlled = byId(toggle.getAttribute("aria-controls"))

    expect(controlled).toHaveAttribute("data-expanded", "true")
    expect(controlled).toHaveAttribute("aria-hidden", "false")
    expect(controlled).not.toHaveAttribute("inert")
  })

  it("hides and reveals a pipeline's agents with the keyboard", async () => {
    const region = show()
    const toggle = part(region, ".audit-pipeline-head")

    expect(within(region).getByText("maintainability_manager run #118")).toBeInTheDocument()

    toggle.focus()
    await userEvent.keyboard("{Enter}")

    expect(toggle).toHaveAttribute("aria-expanded", "false")
    const controlled = byId(toggle.getAttribute("aria-controls"))
    expect(controlled).toHaveAttribute("aria-hidden", "true")
    expect(controlled).toHaveAttribute("inert")
    // Rows stay mounted, so reopening restores the same agent runs.
    expect(within(region).getByText("maintainability_manager run #118")).toBeInTheDocument()

    await userEvent.click(toggle)

    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(byId(toggle.getAttribute("aria-controls"))).toHaveAttribute("aria-hidden", "false")
    expect(byId(toggle.getAttribute("aria-controls"))).not.toHaveAttribute("inert")
  })

  it("folds pipelines independently", async () => {
    const region = show()
    const toggles = region.querySelectorAll(".audit-pipeline-head")

    await userEvent.click(toggles[0])

    expect(toggles[0]).toHaveAttribute("aria-expanded", "false")
    expect(toggles[1]).toHaveAttribute("aria-expanded", "true")
  })

  it("marks the folded pipeline's own progress and the audit total visible", async () => {
    const region = show()

    await userEvent.click(part(region, ".audit-pipeline-head"))

    expect(within(part(region, ".audit-pipeline-head")).getByText("1 of 2 agents")).toBeInTheDocument()
    expect(within(part(region, ".audit-status-head")).getByText("1 of 2 agents")).toBeInTheDocument()
  })
})

describe("AuditStatusView state accents", () => {
  it("exposes the state on the audit, its pipelines and its agents for colouring", () => {
    // show() returns the audit region itself, which is the .audit-status node.
    const region = show({
      ...audit,
      state: "partial",
      pipelines: [
        { id: "maintainability", state: "completed", agents: [{ ...audit.pipelines[0]!.agents[0]!, state: "completed" }] },
        { id: "security", state: "failed", agents: [] },
      ],
    })

    expect(region).toHaveAttribute("data-state", "partial")
    const pipelines = region.querySelectorAll(".audit-pipeline")
    expect(pipelines[0]).toHaveAttribute("data-state", "completed")
    expect(pipelines[1]).toHaveAttribute("data-state", "failed")
    expect(region.querySelector(".audit-agent")).toHaveAttribute("data-state", "completed")
  })

  // Each level carries the state, so one CSS rule colours audit, pipeline and
  // agent borders consistently instead of three sets of state classes.
  it.each(["waiting", "running", "completed", "partial", "failed"] as const)(
    "gives the %s state its own accent at every level",
    (state) => {
      const region = show({
        ...audit,
        state,
        pipelines: [{ id: "security", state, agents: [{ ...audit.pipelines[0]!.agents[0]!, state }] }],
      })

      expect(region).toHaveAttribute("data-state", state)
      expect(region.querySelector(".audit-pipeline")).toHaveAttribute("data-state", state)
      expect(region.querySelector(".audit-agent")).toHaveAttribute("data-state", state)
    },
  )
})

describe("AuditStatusView Spanish", () => {
  afterEach(async () => {
    await changeLanguage("en")
  })

  it("translates chrome while keeping backend identifiers and errors verbatim", async () => {
    await changeLanguage("es")

    const region = show({
      ...audit,
      error: "El pipeline de seguridad no pudo iniciarse.",
      pipelines: [{
        id: "security",
        state: "failed",
        agents: [{
          id: 121, agentType: "security_scanner", state: "completed",
          inputTokens: 1000, outputTokens: 2000,
          startedAt: "2026-10-17T10:00:00Z", finishedAt: "2026-10-17T10:01:00Z", error: null,
        }],
      }],
    })

    expect(screen.getByRole("group", { name: "Estado de la auditoría" })).toBeInTheDocument()
    expect(within(region).getByRole("link", { name: "Abrir acme/Payments" })).toHaveAttribute("href", "/projects/5/audits")
    expect(within(part(region, ".audit-status-head")).getByText("Auditoría #41")).toBeInTheDocument()
    expect(within(part(region, ".audit-status-head")).getByText("En ejecución")).toBeInTheDocument()
    expect(within(part(region, ".audit-pipeline-head")).getByText("Seguridad")).toBeInTheDocument()
    expect(within(part(region, ".audit-pipeline-head")).getByText("1 de 1 agentes")).toBeInTheDocument()
    // Only the surrounding copy translates; the agent type stays verbatim.
    expect(within(region).getByText("Ejecución de security_scanner #121")).toBeInTheDocument()
    expect(within(region).getByText("1000 entrada · 2000 salida")).toBeInTheDocument()
    expect(within(region).getByText("El pipeline de seguridad no pudo iniciarse.")).toBeInTheDocument()
  })
})
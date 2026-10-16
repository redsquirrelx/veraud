import { afterEach, describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AgentMenu } from "./AgentMenu.tsx"
import { AgentTokenUsage } from "./AgentTokenUsage.tsx"
import { changeLanguage } from "../i18n/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

const running: AgentExecution = {
  id: 11,
  evaluationId: 7,
  agentType: "analyzer",
  status: "Running",
  result: null,
  error: null,
  inputTokens: null,
  outputTokens: null,
  createdAt: "2026-01-01",
  startedAt: "2026-01-01",
  finishedAt: null,
}

const waiting: AgentExecution = {
  ...running,
  id: 12,
  status: "Waiting",
  startedAt: null,
}

describe("AgentMenu", () => {
  it("renders nothing before any run", () => {
    const { container } = render(<AgentMenu executions={[]} />)

    expect(container.innerHTML).toBe("")
  })

  it("keeps finished runs with their final status", async () => {
    const { rerender } = render(<AgentMenu executions={[running]} />)

    expect(screen.getByText("analyzer run #11")).toBeDefined()

    rerender(
      <AgentMenu
        executions={[{ ...running, status: "Completed", result: "{\"kind\":\"library\"}", finishedAt: "2026-01-01" }]}
      />
    )

    expect(screen.getByText("analyzer run #11")).toBeDefined()
    expect(screen.getByText("Completed")).toBeDefined()
    expect(screen.getByLabelText("Done")).toBeDefined()
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull()
  })

  it("collapsed prefers running over waiting", () => {
    render(<AgentMenu executions={[waiting, running]} />)

    expect(screen.getByText("analyzer run #11")).toBeDefined()
    expect(screen.queryByText("analyzer run #12")).toBeNull()
  })

  it("collapsed shows the last run when all are done", () => {
    render(
      <AgentMenu
        executions={[
          { ...running, status: "Completed", result: "{}", finishedAt: "2026-01-01" },
          { ...waiting, status: "Failed", error: "boom", finishedAt: "2026-01-01" },
        ]}
      />
    )

    expect(screen.getByText("analyzer run #12")).toBeDefined()
    expect(screen.queryByText("analyzer run #11")).toBeNull()
  })

  it("expanded shows newest first", async () => {
    const { container } = render(<AgentMenu executions={[running, waiting]} />)

    await userEvent.click(screen.getByRole("button", { name: "Expand agents" }))

    const cards = container.querySelectorAll(".agent-menu-list .ui-card")
    expect(cards.length).toBe(2)
    expect(cards[0]?.textContent).toContain("analyzer run #12")
    expect(cards[1]?.textContent).toContain("analyzer run #11")
  })

  it("closes through its X button and reopens on new runs", async () => {
    const { rerender } = render(<AgentMenu executions={[running]} />)

    await userEvent.click(screen.getByRole("button", { name: "Close agent menu" }))

    await waitFor(() => {
      expect(screen.queryByText("analyzer run #11")).toBeNull()
    })

    rerender(<AgentMenu executions={[running, waiting]} />)

    expect(screen.getByText("analyzer run #11")).toBeDefined()
  })
})

describe("AgentMenu Spanish", () => {
  afterEach(async () => {
    await changeLanguage("en")
  })

  it("translates menu chrome and token usage while keeping content ids", async () => {
    await changeLanguage("es")

    expect(document.documentElement.lang).toBe("es")

    render(<AgentMenu executions={[running]} />)

    expect(screen.getByRole("status", { name: "Ejecuciones de agentes" })).toBeDefined()
    expect(screen.getByText("Ejecuciones de agentes (1)")).toBeDefined()
    expect(screen.getByRole("button", { name: "Expandir agentes" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Cerrar el menú de agentes" })).toBeDefined()
    // Agent type names stay untranslated inside a reordered translated sentence.
    expect(screen.getByText("Ejecución n.º 11 de analyzer")).toBeDefined()
    expect(screen.getByText("En ejecución")).toBeDefined()
    expect(screen.getByText("Uso de tokens no informado")).toBeDefined()
    expect(screen.getByText("Sin límite absoluto registrado")).toBeDefined()
    expect(screen.getByText("Sin presupuesto inicial registrado")).toBeDefined()
  })

  it("translates token budget states and breakdown labels", async () => {
    await changeLanguage("es")

    const budgeted: AgentExecution = {
      ...running,
      inputTokens: 1000,
      outputTokens: 500,
      estimatedTokens: null,
      configuration: {
        model: { id: 1, name: "model", providerId: 2, providerName: "provider" },
        credential: { id: 3, name: "credential", providerId: 2, providerName: "provider" },
        temperature: null,
        maxTokens: null,
        tokenBudget: 1000,
        absoluteTokenLimit: 2000,
      },
    }
    render(<AgentTokenUsage execution={budgeted} />)

    expect(screen.getByText("Dentro de la tolerancia")).toBeDefined()
    expect(screen.getByText("Límite absoluto: 2000 tokens")).toBeDefined()
    expect(screen.getByText("Desglose de tokens")).toBeDefined()
    expect(screen.getByText("Entrada (informada)")).toBeDefined()
  })
})

import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { AgentTokenUsage } from "./AgentTokenUsage.tsx"
import { changeLanguage } from "../i18n/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

const running: AgentExecution = {
  id: 11, evaluationId: 7, agentType: "analyzer", status: "Running", result: null, error: null,
  inputTokens: null, outputTokens: null, createdAt: "2026-01-01", startedAt: "2026-01-01", finishedAt: null,
}

describe("AgentTokenUsage Spanish", () => {
  afterEach(async () => { await changeLanguage("en") })

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

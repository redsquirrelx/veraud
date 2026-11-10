import { afterEach, describe, expect, it, vi } from "vitest"
import { startArchitectureContext } from "./architectureContextApi.ts"
import { ProjectPipelineError } from "./projectPipelineErrors.ts"

const original = globalThis.fetch
afterEach(() => { globalThis.fetch = original })

describe("architecture context launch", () => {
  it("identifies model/credential configuration rejection without displaying backend/provider details", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "private detail",
      agents: [{ agentType: "architecture_context", reason: "Missing model and credential" }],
    }), { status: 422 }))
    const pending = startArchitectureContext({ projectId: 2, branch: "main", commitHash: "a".repeat(40) }, new AbortController().signal)
    await expect(pending).rejects.toBeInstanceOf(ProjectPipelineError)
    await expect(pending).rejects.toMatchObject({ labelKey: "analyze.pipeline.contextConfigurationError" })
  })

  it("does not call other 422 responses a credential problem", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "Already running" }), { status: 422 }))
    await expect(startArchitectureContext({ projectId: 2, branch: "main", commitHash: "a".repeat(40) }, new AbortController().signal))
      .rejects.toMatchObject({ status: 422, messageSource: "client" })
  })
})

import { afterEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { getQualityAuditConfiguration, type AuditConfigurationHistory } from "./qualityAuditApi.ts"
import { ReuseAuditConfiguration } from "./ReuseAuditConfiguration.tsx"
import { listAgentSettings } from "../../infrastructure/http-client/httpClient.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getQualityAuditConfiguration: vi.fn() }))
vi.mock("../../infrastructure/http-client/httpClient.ts", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../infrastructure/http-client/httpClient.ts")>(), listAgentSettings: vi.fn(),
}))
afterEach(async () => { cleanup(); vi.resetAllMocks(); await changeLanguage("en") })
const catalog = { agents: [], loading: false, failed: false, retry: vi.fn() }

describe("reuse configuration action", () => {
  it("loads the catalog only after an explicit history reuse action", async () => {
    vi.mocked(listAgentSettings).mockResolvedValue([{ agentType: "security", configured: true, configuration: null,
      qualityAttributes: ["security"], workflowIds: [], availability: "available" }])
    vi.mocked(getQualityAuditConfiguration).mockResolvedValue({ configuration: {
      version: 1, branch: "main", commitHash: "a".repeat(40), attributes: ["security"],
      scopes: [{ id: "security", requiredAgents: [], subcharacteristics: [], techniques: [], investigators: [] }],
    }, invocations: [] })
    const onReuse = vi.fn()
    render(<ReuseAuditConfiguration projectId={5} auditId={8} available lazyCatalog
      catalog={{ ...catalog, loading: true }} disabled={false} onReuse={onReuse} />)
    expect(listAgentSettings).not.toHaveBeenCalled()
    expect(getQualityAuditConfiguration).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole("button", { name: "Reuse configuration" }))
    expect(listAgentSettings).toHaveBeenCalledExactlyOnceWith(expect.any(AbortSignal))
    expect(onReuse).toHaveBeenCalledWith({ maintainability: {}, security: true, functionalAdequacy: false, adjusted: false })
  })

  it("preserves the form on failure and translates the error", async () => {
    vi.mocked(getQualityAuditConfiguration).mockRejectedValue(new Error("offline"))
    const onReuse = vi.fn()
    render(<ReuseAuditConfiguration projectId={5} auditId={8} available catalog={catalog} disabled={false} onReuse={onReuse} />)
    await userEvent.click(screen.getByRole("button", { name: "Reuse configuration" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the configuration. Try again.")
    expect(onReuse).not.toHaveBeenCalled()
    await changeLanguage("es")
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar la configuración. Inténtalo de nuevo.")
  })

  it("aborts requests on unmount so a late response cannot alter a different form", async () => {
    let finish!: (value: AuditConfigurationHistory) => void
    vi.mocked(getQualityAuditConfiguration).mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const onReuse = vi.fn()
    const { unmount } = render(<ReuseAuditConfiguration projectId={5} auditId={8} available catalog={catalog} disabled={false} onReuse={onReuse} />)
    await userEvent.click(screen.getByRole("button", { name: "Reuse configuration" }))
    const signal = vi.mocked(getQualityAuditConfiguration).mock.calls[0]![2]!
    unmount()
    expect(signal.aborted).toBe(true)
    await act(async () => { finish({ configuration: null, invocations: [] }) })
    expect(onReuse).not.toHaveBeenCalled()
  })
})

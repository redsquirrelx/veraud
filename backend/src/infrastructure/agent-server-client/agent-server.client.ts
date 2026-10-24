import { logger } from "../../config/logger.js"
import { executionRequest } from "./execution-request.js"
import type { AgentRunConfig, ModelAccessVerifier } from "../../modules/agent-settings/agent-configuration.js"
import { ModelAccessError, type ModelAccessErrorCode } from "../../modules/agent-settings/model-access-error.js"
import { AgentCatalogError, parseAgentCatalog, type AgentCatalog, type AgentCatalogSource } from "../../modules/agent-settings/agent-catalog.js"

/** The agent-server answers /api/agents/run with the agent's own output, opaque
 *  to this side: each agent defines its shape and the backend stores it as JSON. */
export type AgentInput = Record<string, unknown>

export interface AgentInvoker {
  /** Runs an agent to completion and returns its serialized output.
   *
   *  `executionId` is the row this run belongs to. The agent-server reports its
   *  own progress back to it over HTTP, so the caller does not write the result
   *  itself. Rejects only when the agent-server could not be reached or the run
   *  failed to start; a run that fails mid-flight is reported by the agent. */
  run(agentType: string, input: AgentInput, executionId: number, config: AgentRunConfig): Promise<AgentInput>
  /** Runs any registered pipeline by name with per-stage ids and configs.
   *
   *  Stage keys must match the agent-server's registered stage names; the
   *  result is keyed by stage artifact name and stays opaque here. */
  runPipelineByName?(pipeline: string, input: PipelineInput, executionIds: Record<string, number>, configs: Record<string, AgentRunConfig>): Promise<Record<string, AgentInput>>
  /** Read an already-started audit; never starts/replays the POST. Null means active. */
  getAuditResult?(runId: string, attributes: string[]): Promise<AgentInput | null>
}

/** What the pipeline needs: only the repository root. Stage inputs are
 *  derived server-side from previous stages. */
/** Opaque operating patches; agent-server validates effective catalog contracts. */
export interface AuditOperatingOptions {
  attribute_options?: Record<string, Record<string, unknown>>
  functional_config?: Record<string, unknown>
  functional_requirements?: { requirement_id: string, description: string }[]
  agent_defaults?: Record<string, unknown>
  security_config?: Record<string, unknown>
  audit_budget?: Record<string, unknown>
  call_limits?: Record<string, unknown>
}

export interface PipelineInput extends AuditOperatingOptions {
  root_path: string
  attributes?: string[]
  commit_hash?: string
}

export class AgentInvocationError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message)
    this.name = "AgentInvocationError"
  }
}

export class AgentTransportError extends AgentInvocationError {
  constructor(readonly code: string, readonly outcomeUncertain: boolean) {
    super(`Agent-server communication interrupted (${code}); execution outcome ${outcomeUncertain ? "unconfirmed" : "not started"}`)
    this.name = "AgentTransportError"
  }
}

export class AuditRunUnavailableError extends Error {}

function transportError(error: unknown): AgentTransportError {
  const entry = error as { code?: string, cause?: { code?: string } } | null
  const rawCode = entry?.cause?.code ?? entry?.code ?? "TRANSPORT_ERROR"
  // Codes only: transport messages can contain connection URLs or credentials.
  const code = /^[A-Z_0-9]+$/.test(rawCode) ? rawCode : "TRANSPORT_ERROR"
  return new AgentTransportError(code, !["ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN", "ENETUNREACH", "EHOSTUNREACH"].includes(code))
}

/** The agent-server holds the request open for the whole run, which for a real
 *  agent is minutes. This is the ceiling on that, not a nudge. */
export const DEFAULT_INVOKE_TIMEOUT_MS = 300_000

/** The pipeline runs two agents back to back under one 600s deadline, so its
 *  ceiling is the pipeline timeout plus headroom for the callbacks to land. */
export const PIPELINE_INVOKE_TIMEOUT_MS = 660_000
export const QUALITY_AUDIT_INVOKE_TIMEOUT_MS = 1_920_000

export class AgentServerClient implements AgentInvoker, ModelAccessVerifier, AgentCatalogSource {
  private log = logger.withTag("agent-server")

  constructor(
    private baseUrl: string,
    private timeoutMs: number = DEFAULT_INVOKE_TIMEOUT_MS,
  ) {}

  async getAgentCatalog(): Promise<AgentCatalog> {
    try {
      const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}/api/agents/catalog`, {
        signal: AbortSignal.timeout(Math.min(this.timeoutMs, 5000)),
      })
      if (!response.ok) throw new AgentCatalogError()
      return parseAgentCatalog(await response.json())
    } catch (error) {
      if (error instanceof AgentCatalogError) throw error
      throw new AgentCatalogError()
    }
  }

  async verify(config: AgentRunConfig): Promise<void> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}/api/agents/verify-access`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(config), signal: AbortSignal.timeout(30_000),
      })
    } catch {
      throw new ModelAccessError("agent_server_unavailable")
    }
    if (!response.ok) {
      const codes: Record<number, ModelAccessErrorCode> = {
        400: "invalid_configuration", 401: "access_denied", 403: "access_denied", 404: "model_not_found",
        422: "invalid_configuration", 429: "rate_limited", 503: "provider_unavailable", 504: "timeout",
      }
      throw new ModelAccessError(codes[response.status] ?? "verification_failed")
    }
    let result: { verified?: boolean }
    try { result = await response.json() as { verified?: boolean } }
    catch { throw new Error("Agent-server returned an invalid model access response") }
    if (result.verified !== true) throw new Error("Agent-server did not confirm model access")
  }

  async run(agentType: string, input: AgentInput, executionId: number, config: AgentRunConfig): Promise<AgentInput> {
    const url = `${this.baseUrl}/api/agents/run`

    this.log.info(`Invoking ${agentType} for execution ${executionId} at ${url}`)

    let response: Response

    try {
      response = await executionRequest(url, { agent_type: agentType, input, execution_id: executionId, config }, this.timeoutMs)
    } catch (error) {
      const failure = transportError(error)
      this.log.error(failure.message)
      throw failure
    }

    if (!response.ok) {
      const detail = "Agent-server rejected the execution; check model access and agent input"
      this.log.error(`Agent ${agentType} failed with ${response.status}`)

      throw new AgentInvocationError(
        `Agent ${agentType} failed with ${response.status}: ${detail}`,
        response.status,
      )
    }

    let payload: { result?: AgentInput }
    try { payload = await response.json() as { result?: AgentInput } }
    catch { throw new AgentInvocationError("Agent-server returned an invalid execution response") }
    const result = payload.result

    this.log.info(`Agent ${agentType} returned`)

    if (result === undefined || result === null) {
      throw new AgentInvocationError(`Agent ${agentType} returned no result`)
    }

    return result
  }

  /** Generic pipeline dispatch: stage keys travel untouched so any registered
   *  pipeline (present or future) runs without a client change. */
  async runPipelineByName(
    pipeline: string,
    input: PipelineInput,
    executionIds: Record<string, number>,
    configs: Record<string, AgentRunConfig>,
    timeoutMs: number = PIPELINE_INVOKE_TIMEOUT_MS,
  ): Promise<Record<string, AgentInput>> {
    const url = `${this.baseUrl}/api/pipelines/${encodeURIComponent(pipeline)}/run`

    this.log.info(
      `Invoking ${pipeline} pipeline for executions ${Object.values(executionIds).join("/")} at ${url}`,
    )

    const qualityAudit = pipeline === "quality-audit"
    // Keep the audit's native 30-minute wall deadline, plus report/cleanup headroom.
    const pipelineTimeoutSeconds = qualityAudit ? 1860 : undefined
    let response: Response

    try {
      response = await executionRequest(url,
        // execution_ids are what the pipeline reports each stage against, so
        // rows are closed by the pipeline rather than by the response.
        {
          input,
          stage_configs: configs,
          execution_ids: executionIds,
          ...(pipelineTimeoutSeconds === undefined ? {} : { timeout_seconds: pipelineTimeoutSeconds }),
        }, qualityAudit ? QUALITY_AUDIT_INVOKE_TIMEOUT_MS : timeoutMs)
    } catch (error) {
      const failure = transportError(error)
      this.log.error(failure.message)
      throw failure
    }

    if (!response.ok) {
      const detail = "Agent-server rejected the pipeline; check model access and agent input"
      this.log.error(`Pipeline ${pipeline} failed with ${response.status}`)

      throw new AgentInvocationError(
        `Pipeline ${pipeline} failed with ${response.status}: ${detail}`,
        response.status,
      )
    }

    let payload: Record<string, AgentInput>
    try { payload = await response.json() as Record<string, AgentInput> }
    catch { throw new AgentInvocationError("Agent-server returned an invalid pipeline response") }

    this.log.info(`Pipeline ${pipeline} returned`)

    return payload
  }

  async getAuditResult(runId: string, attributes: string[]): Promise<AgentInput | null> {
    const base = `${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}`
    const read = async (url: string) => {
      const response = await fetch(url, { signal: AbortSignal.timeout(30_000) })
      if (response.status === 404) throw new AuditRunUnavailableError("The agent-server no longer retains this audit run")
      if (!response.ok) throw new Error(`Audit reconciliation returned HTTP ${response.status}`)
      return response
    }
    const snapshot = await (await read(base)).json() as AgentInput
    if (snapshot["run_id"] !== runId) throw new Error("Audit reconciliation returned a different run")
    if (["queued", "running"].includes(String(snapshot["status"]))) return null
    if (!["completed", "partial", "failed", "cancelled"].includes(String(snapshot["status"]))) {
      throw new Error("Audit reconciliation returned an invalid state")
    }
    const report = await (await read(`${base}/report`)).json() as AgentInput
    const document = await (await read(`${base}/report.docx`)).arrayBuffer()
    return { attributes, status: snapshot["status"], run_id: runId, report,
      blackboard: snapshot, docx_base64: Buffer.from(document).toString("base64") }
  }
}

import { logger } from "../../config/logger.js"
import { executionRequest } from "./execution-request.js"
import type { TraceEnvelope } from "../trace-writer.js"
import { readExecutionErrorDetail } from "../../modules/agent-execution/execution-error-detail.js"
import { parseArtifactManifest } from "../../modules/quality-audit/audit-artifacts.js"
import { writeTraceEvent, traceFailureDetails } from "../trace-writer.js"
import type { AgentRunConfig, ModelAccessVerifier } from "../../modules/agent-settings/agent-configuration.js"
import { ModelAccessError, type ModelAccessErrorCode } from "../../modules/agent-settings/model-access-error.js"
import { AgentCatalogError, parseAgentCatalog, type AgentCatalog, type AgentCatalogSource } from "../../modules/agent-settings/agent-catalog.js"

/** The agent-server answers /api/agents/run with the agent's own output, opaque
 *  to this side: each agent defines its shape and the backend stores it as JSON. */
export type AgentInput = Record<string, unknown>

export interface VerificationSuiteOptions {
  llm?: "none" | "provider"
  config?: AgentRunConfig | undefined
  allowExecution?: boolean
  timeoutMs?: number
  action?: "create" | "execute"
  greenControl?: string | undefined
  attemptId?: string
  targetCommit?: string | undefined
  group?: string | undefined
  /** Backend row that tracks this build over the agent-execution callback channel. */
  executionId?: number | undefined
}

export interface AgentInvoker {
  /** Runs an agent to completion and returns its serialized output.
   *
   *  `executionId` is the row this run belongs to. The agent-server reports its
   *  own progress back to it over HTTP, so the caller does not write the result
   *  itself. Rejects only when the agent-server could not be reached or the run
   *  failed to start; a run that fails mid-flight is reported by the agent. */
  run(agentType: string, input: AgentInput, executionId: number, config: AgentRunConfig, trace?: TraceEnvelope): Promise<AgentInput>
  /** Run the finding-test-generation pipeline for an audit run and return
   *  the build summary (table data and ZIP location). */
  requestVerificationSuite?(runId: string, options?: VerificationSuiteOptions): Promise<AgentInput>
  /** Read the state of a verification-suite build; null means not built yet (404). */
  getVerificationSuite?(runId: string): Promise<AgentInput | null>
  /** Stream the raw bytes of the generated verification-suite ZIP. */
  downloadVerificationSuite?(runId: string): Promise<Response>
  /** Runs any registered pipeline by name with per-stage ids and configs.
   *
   *  Stage keys must match the agent-server's registered stage names; the
   *  result is keyed by stage artifact name and stays opaque here. */
  runPipelineByName?(pipeline: string, input: PipelineInput, executionIds: Record<string, number>, configs: Record<string, AgentRunConfig>, timeoutMs?: number, trace?: TraceEnvelope): Promise<Record<string, AgentInput>>
  /** Read an already-started audit; never starts/replays the POST. Null means active. */
  /** Read compact metadata for an already-started audit; never starts/replays the POST. Null means active. */
  getAuditArtifacts?(runId: string, attributes: string[]): Promise<AgentInput | null>
  getAuditResult?(runId: string, attributes: string[]): Promise<AgentInput | null>
  /** Read published records without reconciling, generating a report or starting work. */
  getAuditSnapshot?(runId: string): Promise<AgentInput>
  cancelAudit?(runId: string): Promise<AgentInput>
}

/** What the pipeline needs: only the repository root. Stage inputs are
 *  derived server-side from previous stages. */
/** Opaque operating patches; agent-server validates effective catalog contracts. */
export interface AuditOperatingOptions {
  request?: Record<string, unknown>
  maintainability_selection?: Record<string, string[]>
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
export class AuditArtifactsUnavailableError extends Error {}

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
/** Verification-suite builds can run well beyond the plain default (paced LLM calls);
 *  kept above the agent-server's own 600s cap for this pipeline. */
export const VERIFICATION_SUITE_INVOKE_TIMEOUT_MS = 1_800_000

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

  async run(agentType: string, input: AgentInput, executionId: number, config: AgentRunConfig, trace?: TraceEnvelope): Promise<AgentInput> {
    const url = `${this.baseUrl}/api/agents/run`

    this.log.info(`Invoking ${agentType} for execution ${executionId}`)
    if (trace) writeTraceEvent(trace, { event: "agent.dispatch.sent", spanId: trace.traceId, status: "running", message: `Dispatching ${agentType}`, details: { method: "POST", path: "/api/agents/run", agentType } })

    let response: Response

    try {
      response = await executionRequest(url, { agent_type: agentType, input, execution_id: executionId, config }, this.timeoutMs, trace ? { "x-veraud-trace-id": trace.traceId, "x-veraud-execution-id": String(trace.executionId), "x-veraud-agent-type": trace.agentType } : {})
    } catch (error) {
      const failure = transportError(error)
      this.log.error(failure.message)
      if (trace) writeTraceEvent(trace, { event: "agent.dispatch.failed", spanId: trace.traceId, status: "error", errorCode: failure.code, message: failure.message, details: traceFailureDetails(failure) })
      throw failure
    }

    if (!response.ok) {
      const detail = "Agent-server rejected the execution; check model access and agent input"
      this.log.error(`Agent ${agentType} failed with ${response.status}`)
      if (trace) writeTraceEvent(trace, { event: "agent.dispatch.rejected", spanId: trace.traceId, status: "error", errorCode: `http_${response.status}`, message: detail, details: { httpStatus: response.status } })

      throw new AgentInvocationError(
        `Agent ${agentType} failed with ${response.status}: ${detail}`,
        response.status,
      )
    }

    let payload: { result?: AgentInput }
    try { payload = await response.json() as { result?: AgentInput } }
    catch {
      if (trace) writeTraceEvent(trace, { event: "agent.dispatch.invalid_response", spanId: trace.traceId, status: "error", errorCode: "invalid_response", message: "Agent-server returned an invalid execution response" })
      throw new AgentInvocationError("Agent-server returned an invalid execution response")
    }
    const result = payload.result

    this.log.info(`Agent ${agentType} returned`)
    if (result === undefined || result === null) {
      if (trace) writeTraceEvent(trace, { event: "agent.dispatch.empty_response", spanId: trace.traceId, status: "error", errorCode: "empty_result", message: "Agent-server returned no result" })
      throw new AgentInvocationError(`Agent ${agentType} returned no result`)
    }

    if (trace) writeTraceEvent(trace, { event: "agent.dispatch.completed", spanId: trace.traceId, status: "ok", message: `${agentType} returned`, details: { resultKeys: Object.keys(result).slice(0, 50) } })
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
    trace?: TraceEnvelope,
  ): Promise<Record<string, AgentInput>> {
    const url = `${this.baseUrl}/api/pipelines/${encodeURIComponent(pipeline)}/run`

    this.log.info(
      `Invoking ${pipeline} pipeline for executions ${Object.values(executionIds).join("/")}`,
    )

    const qualityAudit = pipeline === "quality-audit"
    // Keep the audit's native 30-minute wall deadline, plus report/cleanup headroom.
    const pipelineTimeoutSeconds = qualityAudit ? 1860 : undefined
    let response: Response

    if (trace) writeTraceEvent(trace, { event: "pipeline.dispatch.sent", spanId: trace.spanId, parentSpanId: trace.traceId, status: "running", message: `Dispatching pipeline ${pipeline}`, details: { pipeline, executionIds: Object.values(executionIds).join(",") } })
    try {
      response = await executionRequest(url,
        // execution_ids are what the pipeline reports each stage against, so
        // rows are closed by the pipeline rather than by the response.
        {
          input,
          stage_configs: configs,
          execution_ids: executionIds,
          ...(pipelineTimeoutSeconds === undefined ? {} : { timeout_seconds: pipelineTimeoutSeconds }),
        }, qualityAudit ? QUALITY_AUDIT_INVOKE_TIMEOUT_MS : timeoutMs,
        trace ? { "x-veraud-trace-id": trace.traceId, "x-veraud-execution-id": String(Object.values(executionIds)[0] ?? 0), "x-veraud-agent-type": pipeline } : {})
    } catch (error) {
      const failure = transportError(error)
      this.log.error(failure.message)
      if (trace) writeTraceEvent(trace, { event: "pipeline.dispatch.failed", spanId: trace.spanId, status: "error", errorCode: failure.code, message: failure.message, details: traceFailureDetails(failure) })
      throw failure
    }

    if (!response.ok) {
      const detail = "Agent-server rejected the pipeline; check model access and agent input"
      this.log.error(`Pipeline ${pipeline} failed with ${response.status}`)
      if (trace) writeTraceEvent(trace, { event: "pipeline.dispatch.rejected", spanId: trace.spanId, status: "error", errorCode: `http_${response.status}`, message: detail, details: { httpStatus: response.status } })

      throw new AgentInvocationError(
        `Pipeline ${pipeline} failed with ${response.status}: ${detail}`,
        response.status,
      )
    }

    let payload: Record<string, AgentInput>
    try { payload = await response.json() as Record<string, AgentInput> }
    catch {
      if (trace) writeTraceEvent(trace, { event: "pipeline.dispatch.invalid_response", spanId: trace.spanId, status: "error", errorCode: "invalid_response", message: "Agent-server returned an invalid pipeline response" })
      throw new AgentInvocationError("Agent-server returned an invalid pipeline response")
    }

    this.log.info(`Pipeline ${pipeline} returned`)
    if (trace) writeTraceEvent(trace, { event: "pipeline.dispatch.completed", spanId: trace.spanId, status: "ok", message: `${pipeline} pipeline returned`, details: { stageKeys: Object.keys(payload) } })

    return payload
  }

  async getAuditArtifacts(runId: string, attributes: string[]): Promise<AgentInput | null> {
    const base = `${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}`
    const response = await fetch(`${base}/summary`, { signal: AbortSignal.timeout(30_000) })
    if (response.status === 404) throw new AuditRunUnavailableError("The agent-server no longer retains this audit run")
    if (!response.ok) throw new Error(`Audit reconciliation returned HTTP ${response.status}`)
    const summary = await response.json() as AgentInput
    if (summary.run_id !== runId) throw new Error("Audit reconciliation returned a different run")
    if (["queued", "running", "cancelling"].includes(String(summary.status))) return null
    if (!["completed", "partial", "failed", "cancelled"].includes(String(summary.status))) {
      throw new Error("Audit reconciliation returned an invalid state")
    }
    const artifactResponse = await fetch(`${base}/artifacts`, { signal: AbortSignal.timeout(30_000) })
    if (!artifactResponse.ok) throw new AuditArtifactsUnavailableError("The audit completed but its published artifacts are unavailable")
    const manifest = parseArtifactManifest(await artifactResponse.json())
    if (manifest === null) throw new AuditArtifactsUnavailableError("The agent-server returned an invalid artifact manifest")
    return { attributes, status: summary.status, run_id: runId, error_detail: readExecutionErrorDetail(summary.error_detail),
      artifacts: manifest }
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
    if (["queued", "running", "cancelling"].includes(String(snapshot["status"]))) return null
    if (!["completed", "partial", "failed", "cancelled"].includes(String(snapshot["status"]))) {
      throw new Error("Audit reconciliation returned an invalid state")
    }
    const report = await (await read(`${base}/report`)).json() as AgentInput
    const document = await (await read(`${base}/report.docx`)).arrayBuffer()
    return { attributes, status: snapshot["status"], run_id: runId, report,
      error_detail: readExecutionErrorDetail(snapshot["error_detail"]),
      blackboard: snapshot, docx_base64: Buffer.from(document).toString("base64") }
  }

  async getAuditSnapshot(runId: string): Promise<AgentInput> {
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}`, {
      signal: AbortSignal.timeout(10_000),
    })
    if (response.status === 404) throw new AuditRunUnavailableError("The agent-server no longer retains this audit run")
    if (!response.ok) throw new Error(`Audit snapshot returned HTTP ${response.status}`)
    const snapshot = await response.json() as AgentInput
    if (snapshot.run_id !== runId) throw new Error("Audit snapshot returned a different run")
    return snapshot
  }

  async cancelAudit(runId: string): Promise<AgentInput> {
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}/cancel`, {
      method: "POST", signal: AbortSignal.timeout(10_000),
    })
    if (response.status === 404) throw new AuditRunUnavailableError("The agent-server no longer retains this audit run")
    if (!response.ok) throw new AgentInvocationError(`Audit cancellation returned HTTP ${response.status}`, response.status)
    const state = await response.json() as AgentInput
    if (state.run_id !== runId || !["queued", "running", "cancelling", "cancelled", "completed", "partial", "failed"].includes(String(state.status))) {
      throw new AgentInvocationError("Agent-server returned an invalid audit cancellation state")
    }
    return state
  }

  async requestVerificationSuite(runId: string, options?: VerificationSuiteOptions): Promise<AgentInput> {
    const url = `${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}/verification-suite`
    let response: Response
    try {
      // Like audit execution, suite creation may take minutes before sending headers.
      // Native fetch has a separate headers timeout even with a longer AbortSignal.
      response = await executionRequest(url, {
        llm: options?.llm ?? "none", allow_execution: options?.allowExecution ?? false,
        config: options?.config,
        action: options?.action ?? "create", green_control: options?.greenControl ?? null,
        attempt_id: options?.attemptId,
        target_commit: options?.targetCommit,
         group: options?.group ?? null,
         execution_id: options?.executionId ?? null,
      }, options?.timeoutMs ?? VERIFICATION_SUITE_INVOKE_TIMEOUT_MS)
    } catch (error) { throw transportError(error) }
    if (response.status === 404) throw new AuditRunUnavailableError("The agent-server no longer retains this audit run")
    if (!response.ok) throw new AgentInvocationError(options?.action === "execute"
      ? `Verification at the requested commit could not complete (HTTP ${response.status}); no alternative checkout was used`
      : `Verification suite request returned HTTP ${response.status}`, response.status)
    const result = await response.json() as AgentInput
    if (result.run_id !== runId) throw new AgentInvocationError("Agent-server returned a different run identity")
    return result
  }

  async getVerificationSuite(runId: string): Promise<AgentInput | null> {
    const url = `${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}/verification-suite`
    const response = await fetch(url, { signal: AbortSignal.timeout(15_000) })
    if (response.status === 404) return null
    if (!response.ok) throw new AgentInvocationError(`Verification suite status returned HTTP ${response.status}`, response.status)
    const result = await response.json() as AgentInput
    if (result.run_id !== runId) throw new AgentInvocationError("Agent-server returned a different run identity")
    return result
  }

  async downloadVerificationSuite(runId: string): Promise<Response> {
    const response = await fetch(`${this.baseUrl.replace(/\/$/, "")}/api/audits/${encodeURIComponent(runId)}/verification-suite.zip`, {
      signal: AbortSignal.timeout(this.timeoutMs),
    })
    if (response.status === 404) throw new AuditRunUnavailableError("Verification suite artifact not found")
    if (!response.ok) throw new AgentInvocationError(`Verification suite download returned HTTP ${response.status}`, response.status)
    return response
  }
}

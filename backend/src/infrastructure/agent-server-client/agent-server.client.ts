import { logger } from "../../config/logger.js"
import type { AgentRunConfig, ModelAccessVerifier } from "../../modules/agent-settings/agent-configuration.js"

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
}

/** What the pipeline needs: only the repository root. Stage inputs are
 *  derived server-side from previous stages. */
export interface PipelineInput {
  root_path: string
}

export class AgentInvocationError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message)
    this.name = "AgentInvocationError"
  }
}

/** The agent-server holds the request open for the whole run, which for a real
 *  agent is minutes. This is the ceiling on that, not a nudge. */
export const DEFAULT_INVOKE_TIMEOUT_MS = 300_000

/** The pipeline runs two agents back to back under one 600s deadline, so its
 *  ceiling is the pipeline timeout plus headroom for the callbacks to land. */
export const PIPELINE_INVOKE_TIMEOUT_MS = 660_000

export class AgentServerClient implements AgentInvoker, ModelAccessVerifier {
  private log = logger.withTag("agent-server")

  constructor(
    private baseUrl: string,
    private timeoutMs: number = DEFAULT_INVOKE_TIMEOUT_MS,
  ) {}

  async verify(config: AgentRunConfig): Promise<void> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}/api/agents/verify-access`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(config), signal: AbortSignal.timeout(30_000),
      })
    } catch {
      throw new Error("Model access could not be verified: agent-server unavailable or timed out")
    }
    if (!response.ok) {
      throw new Error(response.status === 422
        ? "Model access denied: check the provider, model, API key and permissions"
        : "Model access could not be verified: provider unavailable or timed out")
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
      response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent_type: agentType, input, execution_id: executionId, config }),
        signal: AbortSignal.timeout(this.timeoutMs),
      })
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      this.log.error(`Could not reach the agent-server: ${reason}`)

      throw new AgentInvocationError(`Could not reach the agent-server: ${reason}`)
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

    let response: Response

    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        // execution_ids are what the pipeline reports each stage against, so
        // rows are closed by the pipeline rather than by the response.
        body: JSON.stringify({
          input,
          stage_configs: configs,
          execution_ids: executionIds,
        }),
        signal: AbortSignal.timeout(timeoutMs),
      })
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      this.log.error(`Could not reach the agent-server: ${reason}`)

      throw new AgentInvocationError(`Could not reach the agent-server: ${reason}`)
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
}

import { logger } from "../../config/logger.js"

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
  run(agentType: string, input: AgentInput, executionId: number): Promise<AgentInput>
  /** Runs the analyzer then the architect as one pipeline.
   *
   *  Optional so tests that only cover single-agent runs need no pipeline
   *  double. `openPipeline` fails both rows when the invoker has no pipeline
   *  support instead of hanging them in Waiting. */
  runPipeline?(input: PipelineInput, executionIds: PipelineExecutionIds): Promise<PipelineResult>
}

/** What the architecture-audit pipeline needs: only the repository root. The
 *  architect's input is derived server-side from the analyzer's output. */
export interface PipelineInput {
  root_path: string
}

export interface PipelineExecutionIds {
  analyzer: number
  architect: number
}

/** Both agent outputs, opaque here like single-agent results. */
export interface PipelineResult {
  analysis: AgentInput
  description: AgentInput
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

export class AgentServerClient implements AgentInvoker {
  private log = logger.withTag("agent-server")

  constructor(
    private baseUrl: string,
    private timeoutMs: number = DEFAULT_INVOKE_TIMEOUT_MS,
  ) {}

  async run(agentType: string, input: AgentInput, executionId: number): Promise<AgentInput> {
    const url = `${this.baseUrl}/api/agents/run`

    this.log.info(`Invoking ${agentType} for execution ${executionId} at ${url}`)

    let response: Response

    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        // No config is sent: the agent-server resolves the model, the
        // temperature and the timeout from its own dev-agents.yaml, and the
        // credential stays on that side instead of crossing the network.
        //
        // execution_id is what the agent-server reports progress against, so this
        // row is closed by the agent rather than by the response below.
        body: JSON.stringify({ agent_type: agentType, input, execution_id: executionId }),
        signal: AbortSignal.timeout(this.timeoutMs),
      })
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      this.log.error(`Could not reach the agent-server: ${reason}`)

      throw new AgentInvocationError(`Could not reach the agent-server: ${reason}`)
    }

    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500)
      this.log.error(`Agent ${agentType} failed with ${response.status}: ${detail}`)

      throw new AgentInvocationError(
        `Agent ${agentType} failed with ${response.status}: ${detail}`,
        response.status,
      )
    }

    const payload = (await response.json()) as { result?: AgentInput }
    const result = payload.result

    this.log.info(`Agent ${agentType} returned`)

    if (result === undefined || result === null) {
      throw new AgentInvocationError(`Agent ${agentType} returned no result`)
    }

    return result
  }

  async runPipeline(
    input: PipelineInput,
    executionIds: PipelineExecutionIds,
    timeoutMs: number = PIPELINE_INVOKE_TIMEOUT_MS,
  ): Promise<PipelineResult> {
    const url = `${this.baseUrl}/api/pipelines/architecture-audit/run`

    this.log.info(
      `Invoking architecture-audit pipeline for executions ${executionIds.analyzer}/${executionIds.architect} at ${url}`,
    )

    let response: Response

    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        // No config is sent, same as single-agent runs: the agent-server
        // resolves models and timeouts from its own dev-agents.yaml.
        //
        // execution_ids are what the pipeline reports each stage against, so
        // both rows are closed by the pipeline rather than by the response.
        body: JSON.stringify({
          input,
          execution_ids: { analyzer: executionIds.analyzer, architect: executionIds.architect },
        }),
        signal: AbortSignal.timeout(timeoutMs),
      })
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      this.log.error(`Could not reach the agent-server: ${reason}`)

      throw new AgentInvocationError(`Could not reach the agent-server: ${reason}`)
    }

    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500)
      this.log.error(`Pipeline failed with ${response.status}: ${detail}`)

      throw new AgentInvocationError(
        `Pipeline failed with ${response.status}: ${detail}`,
        response.status,
      )
    }

    const payload = (await response.json()) as Partial<PipelineResult>

    this.log.info(`Pipeline returned`)

    if (payload.analysis === undefined || payload.description === undefined) {
      throw new AgentInvocationError(`Pipeline returned no result`)
    }

    return { analysis: payload.analysis, description: payload.description }
  }
}
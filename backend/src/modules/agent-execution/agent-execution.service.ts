import { logger } from "../../config/logger.js"
import type { AgentExecutionEvent } from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import type { AgentInput, AgentInvoker, PipelineExecutionIds, PipelineConfigs } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentTargetResolver } from "../../infrastructure/agent-target/agent-target.resolver.js"
import { assertDirectCheckout, sanitizeDirectInput } from "../../infrastructure/agent-target/direct-input.guard.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import type { AgentRunConfig } from "../agent-settings/agent-configuration.js"
import type { ProjectArchitectureAnalysisRequest } from "../project/project.service.js"
import { ANALYZER_AGENT_TYPE, ARCHITECT_AGENT_TYPE, PROJECT_ARCHITECTURE_PIPELINE_NAME, PROJECT_ARCHITECTURE_PIPELINE_STAGES } from "../agent-settings/agent-types.js"
import {
  INITIAL_STATUS,
  type AgentExecutionCompletion,
  type AgentExecutionStatus,
  type AgentExecutionStore,
  type NewAgentExecution,
  type StoredAgentExecution,
} from "./agent-execution.repository.js"

export class AgentExecutionNotFoundError extends Error {
  constructor(id: number) {
    super(`Agent execution ${id} not found`)
    this.name = "AgentExecutionNotFoundError"
  }
}

export { ANALYZER_AGENT_TYPE, ARCHITECT_AGENT_TYPE } from "../agent-settings/agent-types.js"

/** The rows one project-architecture pipeline drives, keyed by stage name. */
export interface ProjectArchitectureExecutions {
  orientation: StoredAgentExecution
  architecture: StoredAgentExecution
  semantic_validation: StoredAgentExecution
}

/** The two rows one architecture-audit pipeline drives, analyzer first. */
export interface PipelineExecutions {
  analyzer: StoredAgentExecution
  architect: StoredAgentExecution
}

export class InvalidCompletionError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "InvalidCompletionError"
  }
}

/** Broadcasts lifecycle changes so the UI follows a run without polling. */
export interface AgentExecutionEvents {
  broadcast(event: AgentExecutionEvent): void
}

export class AgentExecutionService {
  private log = logger.withTag("agent-execution")

  constructor(
    private executions: AgentExecutionStore,
    private agents: AgentInvoker,
    private targets: AgentTargetResolver,
    private events: AgentExecutionEvents,
    private workspaceDir: string,
    private settings: AgentSettingsService,
  ) {}

  /**
   * Registers an invocation on behalf of an agent and starts it.
   *
   * The row is created Waiting and returned straight away, then the run happens
   * in the background: an agent takes minutes and the caller must not hold a
   * request open for it.
   *
   * Everything after this line is fire-and-forget. The row is closed by the agent
   * reporting back over HTTP, not from the response to this call, because the
   * agent is the only side that knows how the run actually went. The one thing
   * that stays here is closing the row when the agent-server could not be reached
   * at all, since nothing else would ever report that.
   */
  async open(agentType: string, evaluationId: number): Promise<StoredAgentExecution> {
    const [configuration] = await this.settings.prepareExecution([agentType])
    const execution = await this.executions.create({
      agentType,
      evaluationId,
      configuration: configuration!,
    } satisfies NewAgentExecution)

    this.log.info(`Opened execution ${execution.id} agentType=${agentType}`)

    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })

    void this.dispatch(execution, configuration!.transport)

    return execution
  }

  /**
   * Registers an architecture-audit pipeline on behalf of an evaluation and
   * starts it.
   *
   * Two rows are created Waiting (analyzer + architect) and returned straight
   * away, then the pipeline runs in the background like a single-agent dispatch:
   * the agent-server reports each stage back over HTTP against its own row, so
   * the caller never waits. Only a failure to start the pipeline at all is
   * written here, to both rows, since nothing else would ever report it.
   */
  async openPipeline(evaluationId: number): Promise<PipelineExecutions> {
    const configurations = await this.settings.prepareExecution([ANALYZER_AGENT_TYPE, ARCHITECT_AGENT_TYPE])
    const analyzerConfig = configurations.find((configuration) => configuration.agentType === ANALYZER_AGENT_TYPE)!
    const architectConfig = configurations.find((configuration) => configuration.agentType === ARCHITECT_AGENT_TYPE)!
    const { analyzer, architect } = await this.executions.createPipeline(evaluationId, configurations)

    this.log.info(
      `Opened pipeline executions ${analyzer.id} (analyzer) + ${architect.id} (architect)`,
    )

    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(analyzer) })
    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(architect) })

    void this.dispatchPipeline(analyzer, architect, { analyzer: analyzerConfig.transport, architect: architectConfig.transport })

    return { analyzer, architect }
  }

  /**
   * Registers a direct invocation with an explicit agent input.
   *
   * Unlike open(), no evaluation or project version is involved: the row is
   * created with evaluationId null and the input travels untouched (except a
   * workspace guard on `root_path`). Traversal outside the workspace throws
   * synchronously; a missing checkout fails the row in the background.
   */
  async openDirect(agentType: string, input: AgentInput): Promise<StoredAgentExecution> {
    const sanitized = sanitizeDirectInput(input, this.workspaceDir)
    const [configuration] = await this.settings.prepareExecution([agentType])

    const execution = await this.executions.create({
      agentType,
      evaluationId: null,
      configuration: configuration!,
    } satisfies NewAgentExecution)

    this.log.info(`Opened direct execution ${execution.id} agentType=${agentType}`)

    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })

    void this.dispatchDirect(execution, sanitized, configuration!.transport)

    return execution
  }

  async openForProject(projectId: number, branch: string, commitHash: string, agentType: string) {
    const [configuration] = await this.settings.prepareExecution([agentType])
    const result = await this.executions.createForProject(projectId, branch, commitHash, configuration!)
    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(result.execution) })
    void this.dispatch(result.execution, configuration!.transport)
    return result
  }

  async openPipelineForProject(projectId: number, branch: string, commitHash: string) {
    const configurations = await this.settings.prepareExecution([ANALYZER_AGENT_TYPE, ARCHITECT_AGENT_TYPE])
    const result = await this.executions.createPipelineForProject(projectId, branch, commitHash, configurations)
    for (const execution of Object.values(result.executions)) {
      this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })
    }
    const configs = {
      analyzer: configurations.find((configuration) => configuration.agentType === ANALYZER_AGENT_TYPE)!.transport,
      architect: configurations.find((configuration) => configuration.agentType === ARCHITECT_AGENT_TYPE)!.transport,
    }
    void this.dispatchPipeline(result.executions.analyzer, result.executions.architect, configs)
    return result
  }

  /**
   * Registers a project-architecture pipeline run: three Waiting rows
   * (orientation, architecture, semantic_validation) under one evaluation,
   * dispatched in the background with per-stage configuration.
   *
   * Only a failure to start at all is written here, to every row, since
   * nothing else would ever report it. Anything after the hand-off is
   * reported stage by stage by the pipeline.
   */
  async openProjectArchitecturePipelineForProject(projectId: number, branch: string, commitHash: string): Promise<ProjectArchitectureAnalysisRequest> {
    const configurations = await this.settings.prepareExecution([...PROJECT_ARCHITECTURE_PIPELINE_STAGES])
    const result = await this.executions.createExecutionsForProject(projectId, branch, commitHash, configurations)
    const executions = {
      orientation: result.executions[PROJECT_ARCHITECTURE_PIPELINE_STAGES[0]]!,
      architecture: result.executions[PROJECT_ARCHITECTURE_PIPELINE_STAGES[1]]!,
      semantic_validation: result.executions[PROJECT_ARCHITECTURE_PIPELINE_STAGES[2]]!,
    }
    for (const execution of Object.values(executions)) {
      this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })
    }
    const configs: Record<string, AgentRunConfig> = {}
    for (const configuration of configurations) configs[configuration.agentType] = configuration.transport
    void this.dispatchPipelineByName(PROJECT_ARCHITECTURE_PIPELINE_NAME, executions, configs)
    return { versionId: result.versionId, evaluationId: result.evaluationId, executions }
  }

  /** Starts the agent and then gets out of the way. Never throws: a failure here
   *  is written to the row instead, because a run that failed silently is worse
   *  than one that failed loudly. */
  private async dispatch(execution: StoredAgentExecution, config: AgentRunConfig): Promise<void> {
    try {
      if (execution.evaluationId === null) {
        throw new Error(`Execution ${execution.id} has no evaluation to resolve`)
      }

      const input = await this.targets.resolve(execution.evaluationId)

      await this.agents.run(execution.agentType, input, execution.id, config)
    } catch (error) {
      // The agent never got far enough to report for itself.
      await this.fail(execution.id, error instanceof Error ? error.message : String(error))
    }
  }

  /** Direct twin of dispatch: the input is already known, only the checkout is
   *  verified before handing it to the agent. Never throws. */
  private async dispatchDirect(execution: StoredAgentExecution, input: AgentInput, config: AgentRunConfig): Promise<void> {
    try {
      assertDirectCheckout(input)

      await this.agents.run(execution.agentType, input, execution.id, config)
    } catch (error) {
      await this.fail(execution.id, error instanceof Error ? error.message : String(error))
    }
  }

  /** Starts the analyzer+architect pipeline and then gets out of the way.
   *  Never throws: a failure here fails both rows, because neither stage got
   *  far enough to report for itself. Anything after the hand-off is reported
   *  stage by stage by the pipeline, including the architect-skipped case. */
  private async dispatchPipeline(analyzer: StoredAgentExecution, architect: StoredAgentExecution, configs: PipelineConfigs): Promise<void> {
    try {
      if (analyzer.evaluationId === null) {
        throw new Error(`Execution ${analyzer.id} has no evaluation to resolve`)
      }

      if (this.agents.runPipeline === undefined) {
        throw new Error("The agent invoker does not support pipelines")
      }

      const input = await this.targets.resolve(analyzer.evaluationId)
      const executionIds: PipelineExecutionIds = { analyzer: analyzer.id, architect: architect.id }

      await this.agents.runPipeline({ root_path: String(input.root_path) }, executionIds, configs)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      await this.fail(analyzer.id, message)
      await this.fail(architect.id, message)
    }
  }

  /** Starts any registered pipeline by name and then gets out of the way.
   *  Never throws: a failure here fails every row, because no stage got far
   *  enough to report for itself. */
  private async dispatchPipelineByName(pipeline: string, executions: Record<string, StoredAgentExecution>, configs: Record<string, AgentRunConfig>): Promise<void> {
    const ids = Object.keys(executions)
    try {
      const first = executions[ids[0]!]!
      if (first.evaluationId === null) {
        throw new Error(`Execution ${first.id} has no evaluation to resolve`)
      }

      if (this.agents.runPipelineByName === undefined) {
        throw new Error("The agent invoker does not support pipelines")
      }

      const input = await this.targets.resolve(first.evaluationId)
      const executionIds: Record<string, number> = {}
      for (const [stage, execution] of Object.entries(executions)) executionIds[stage] = execution.id

      await this.agents.runPipelineByName(pipeline, { root_path: String(input.root_path) }, executionIds, configs)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      for (const execution of Object.values(executions)) await this.fail(execution.id, message)
    }
  }

  /** Marks an invocation as in flight. Optional: the agent-server may skip it. */
  async markRunning(id: number): Promise<StoredAgentExecution> {
    await this.require(id)

    return this.executions.markRunning(id)
  }

  /**
   * Closes an invocation with the agent's outcome.
   *
   * `result` is the serialized agent output and stays opaque here: each agent
   * defines its own shape, so the backend has no reason to know its fields.
   */
  async complete(id: number, completion: AgentExecutionCompletion): Promise<StoredAgentExecution> {
    const existing = await this.require(id)

    if (existing.status === "Completed" || existing.status === "Failed") {
      // A late or duplicated callback must not overwrite a finished run.
      return existing
    }

    if (completion.status === "Failed" && !completion.error) {
      throw new InvalidCompletionError("status Failed requires an error message")
    }

    return this.executions.complete(id, completion)
  }

  async findById(id: number): Promise<StoredAgentExecution> {
    return this.require(id)
  }

  private async close(id: number, completion: AgentExecutionCompletion): Promise<void> {
    const execution = await this.complete(id, completion)

    this.log.info(`Execution ${id} closed as ${execution.status}`)

    this.events.broadcast({ type: "agent-execution.updated", execution: toEvent(execution) })
  }

  /** Records a failure without letting the recording itself throw: the row is
   *  the only trace of this run, so an error while writing it must not silence
   *  the one that caused it. */
  private async fail(id: number, message: string): Promise<void> {
    this.log.error(`Execution ${id} failed: ${message}`)

    try {
      await this.close(id, {
        status: "Failed",
        result: null,
        error: message.slice(0, 2000),
        inputTokens: null,
        outputTokens: null,
      })
    } catch (error) {
      this.log.error(`Could not record the failure of execution ${id}: ${error}`)
    }
  }

  private async require(id: number): Promise<StoredAgentExecution> {
    const execution = await this.executions.findById(id)

    if (execution === null) {
      throw new AgentExecutionNotFoundError(id)
    }

    return execution
  }
}

function toEvent(execution: StoredAgentExecution): AgentExecutionEvent["execution"] {
  return {
    id: execution.id,
    evaluationId: execution.evaluationId,
    agentType: execution.agentType,
    status: execution.status,
    result: execution.result,
    error: execution.error,
    inputTokens: execution.inputTokens,
    outputTokens: execution.outputTokens,
    createdAt: execution.createdAt,
    startedAt: execution.startedAt,
    finishedAt: execution.finishedAt,
  }
}

export { INITIAL_STATUS }
export type { AgentExecutionStatus, AgentInput, StoredAgentExecution }

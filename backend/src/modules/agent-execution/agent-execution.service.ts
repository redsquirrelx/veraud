import { logger } from "../../config/logger.js"
import type { AgentExecutionEvent } from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import type { AgentInput, AgentInvoker } from "../../infrastructure/agent-server-client/agent-server.client.js"
import type { AgentTargetResolver } from "../../infrastructure/agent-target/agent-target.resolver.js"
import { assertDirectCheckout, sanitizeDirectInput } from "../../infrastructure/agent-target/direct-input.guard.js"
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
    const execution = await this.executions.create({
      agentType,
      evaluationId,
    } satisfies NewAgentExecution)

    this.log.info(`Opened execution ${execution.id} agentType=${agentType}`)

    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })

    void this.dispatch(execution)

    return execution
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

    const execution = await this.executions.create({
      agentType,
      evaluationId: null,
    } satisfies NewAgentExecution)

    this.log.info(`Opened direct execution ${execution.id} agentType=${agentType}`)

    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })

    void this.dispatchDirect(execution, sanitized)

    return execution
  }

  /** Starts the agent and then gets out of the way. Never throws: a failure here
   *  is written to the row instead, because a run that failed silently is worse
   *  than one that failed loudly. */
  private async dispatch(execution: StoredAgentExecution): Promise<void> {
    try {
      if (execution.evaluationId === null) {
        throw new Error(`Execution ${execution.id} has no evaluation to resolve`)
      }

      const input = await this.targets.resolve(execution.evaluationId)

      await this.agents.run(execution.agentType, input, execution.id)
    } catch (error) {
      // The agent never got far enough to report for itself.
      await this.fail(execution.id, error instanceof Error ? error.message : String(error))
    }
  }

  /** Direct twin of dispatch: the input is already known, only the checkout is
   *  verified before handing it to the agent. Never throws. */
  private async dispatchDirect(execution: StoredAgentExecution, input: AgentInput): Promise<void> {
    try {
      assertDirectCheckout(input)

      await this.agents.run(execution.agentType, input, execution.id)
    } catch (error) {
      await this.fail(execution.id, error instanceof Error ? error.message : String(error))
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
    const execution = await this.executions.complete(id, completion)

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
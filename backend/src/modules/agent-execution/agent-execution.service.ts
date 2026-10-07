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

export class AgentExecutionService {
  constructor(private executions: AgentExecutionStore) {}

  /**
   * Registers an invocation on behalf of an agent. The backend creates the row
   * and hands the id to the agent-server, which only ever updates it.
   */
  open(agentType: string, evaluationId: number): Promise<StoredAgentExecution> {
    return this.executions.create({
      agentType,
      evaluationId,
    } satisfies NewAgentExecution)
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

  private async require(id: number): Promise<StoredAgentExecution> {
    const execution = await this.executions.findById(id)

    if (execution === null) {
      throw new AgentExecutionNotFoundError(id)
    }

    return execution
  }
}

export { INITIAL_STATUS }
export type { AgentExecutionStatus, StoredAgentExecution }
import type { PrismaClient } from "../../generated/prisma/client.js"

export type AgentExecutionStatus =
  | "Waiting"
  | "Running"
  | "Completed"
  | "Failed"

/** An agent invocation starts Waiting: the request was accepted, nothing has
 *  run yet. Title case, matching the `task` module. */
export const INITIAL_STATUS: AgentExecutionStatus = "Waiting"

export interface NewAgentExecution {
  agentType: string
  evaluationId: number
}

export interface AgentExecutionCompletion {
  status: AgentExecutionStatus
  result: string | null
  error: string | null
  inputTokens: number | null
  outputTokens: number | null
}

export interface StoredAgentExecution {
  id: number
  evaluationId: number
  agentType: string
  status: AgentExecutionStatus
  result: string | null
  error: string | null
  inputTokens: number | null
  outputTokens: number | null
  createdAt: Date
  startedAt: Date | null
  finishedAt: Date | null
}

export interface AgentExecutionStore {
  create(data: NewAgentExecution): Promise<StoredAgentExecution>
  complete(id: number, data: AgentExecutionCompletion): Promise<StoredAgentExecution>
  markRunning(id: number): Promise<StoredAgentExecution>
  findById(id: number): Promise<StoredAgentExecution | null>
}

export class AgentExecutionRepository implements AgentExecutionStore {
  constructor(private db: PrismaClient) {}

  async create(data: NewAgentExecution): Promise<StoredAgentExecution> {
    const execution = await this.db.agentExecution.create({
      data: {
        agentType: data.agentType,
        evaluationId: data.evaluationId,
        status: INITIAL_STATUS,
      },
    })

    return this.toStored(execution)
  }

  async complete(id: number, data: AgentExecutionCompletion): Promise<StoredAgentExecution> {
    const execution = await this.db.agentExecution.update({
      where: { id },
      data: {
        status: data.status,
        result: data.result,
        error: data.error,
        inputTokens: data.inputTokens,
        outputTokens: data.outputTokens,
        finishedAt: new Date(),
      },
    })

    return this.toStored(execution)
  }

  async markRunning(id: number): Promise<StoredAgentExecution> {
    const execution = await this.db.agentExecution.update({
      where: { id },
      data: { status: "Running", startedAt: new Date() },
    })

    return this.toStored(execution)
  }

  async findById(id: number): Promise<StoredAgentExecution | null> {
    const execution = await this.db.agentExecution.findUnique({ where: { id } })

    if (execution === null) {
      return null
    }

    return this.toStored(execution)
  }

  private toStored(execution: {
    id: number
    evaluationId: number
    agentType: string
    status: string
    result: string | null
    error: string | null
    inputTokens: number | null
    outputTokens: number | null
    createdAt: Date
    startedAt: Date | null
    finishedAt: Date | null
  }): StoredAgentExecution {
    return {
      id: execution.id,
      evaluationId: execution.evaluationId,
      agentType: execution.agentType,
      status: execution.status as AgentExecutionStatus,
      result: execution.result,
      error: execution.error,
      inputTokens: execution.inputTokens,
      outputTokens: execution.outputTokens,
      createdAt: execution.createdAt,
      startedAt: execution.startedAt,
      finishedAt: execution.finishedAt,
    }
  }
}
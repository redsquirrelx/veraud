import { Prisma, type PrismaClient } from "../../generated/prisma/client.js"

/** agent_type and evaluation_id are both foreign keys, so an unknown value is a
 *  bad request rather than a server fault. Prisma reports that as P2003. */
export class UnknownExecutionTargetError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "UnknownExecutionTargetError"
  }
}

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
  evaluationId: number | null
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
  evaluationId: number | null
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
    try {
      const execution = await this.db.agentExecution.create({
        data: {
          agentType: data.agentType,
          evaluationId: data.evaluationId,
          status: INITIAL_STATUS,
        },
      })

      return this.toStored(execution)
    } catch (error) {
      if (error instanceof Prisma.PrismaClientKnownRequestError && error.code === "P2003") {
        throw new UnknownExecutionTargetError(
          data.evaluationId === null
            ? `No agent type ${data.agentType} is registered`
            : `No agent type ${data.agentType} is registered, or evaluation ${data.evaluationId} does not exist`,
        )
      }

      throw error
    }
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
    evaluationId: number | null
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
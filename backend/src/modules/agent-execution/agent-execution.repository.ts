import { Prisma, type PrismaClient } from "../../generated/prisma/client.js"
import type { AgentSettingsRepository, AgentConfiguration } from "../agent-settings/agent-settings.repository.js"
import { AgentConfigurationError, type PreparedAgentConfiguration } from "../agent-settings/agent-configuration.js"

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
  configuration: PreparedAgentConfiguration
}

export interface AgentExecutionCompletion {
  status: AgentExecutionStatus
  result: string | null
  error: string | null
  inputTokens: number | null
  outputTokens: number | null
  estimatedTokens?: number | null
  accountedTokens?: number | null
  interruptionReason?: string | null
}

/** Cumulative usage, never a delta. Estimates are distinct from provider counts. */
export interface AgentExecutionUsage {
  inputTokens: number | null
  outputTokens: number | null
  estimatedTokens: number
  accountedTokens: number
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
  estimatedTokens: number | null
  accountedTokens: number | null
  interruptionReason: string | null
  createdAt: Date
  startedAt: Date | null
  finishedAt: Date | null
  configuration?: AgentConfiguration | null
}

export interface AgentExecutionStore {
  create(data: NewAgentExecution): Promise<StoredAgentExecution>
  complete(id: number, data: AgentExecutionCompletion): Promise<StoredAgentExecution>
  markRunning(id: number): Promise<StoredAgentExecution>
  updateUsage(id: number, usage: AgentExecutionUsage): Promise<StoredAgentExecution>
  findById(id: number): Promise<StoredAgentExecution | null>
  /** Overwrites the stored result of a finished row without touching its
   *  status: used to attach the pipeline-level diagram to the architecture
   *  row after every stage already reported. */
  patchResult(id: number, result: string): Promise<StoredAgentExecution>
  /** One row per configuration, keyed by agent type, under a fresh evaluation.
   *  Works for any present or future pipeline; empty lists are rejected. */
  createExecutionsForProject(projectId: number, branch: string, commitHash: string, configurations: PreparedAgentConfiguration[]): Promise<{ versionId: number, evaluationId: number, executions: Record<string, StoredAgentExecution> }>
}

export class AgentExecutionRepository implements AgentExecutionStore {
  constructor(private db: PrismaClient, private settings: AgentSettingsRepository) {}

  async create(data: NewAgentExecution): Promise<StoredAgentExecution> {
    try {
      return await this.db.$transaction(async (tx) => {
        await this.assertCurrent(tx, data.configuration)
        const execution = await tx.agentExecution.create({
          data: {
            agentType: data.agentType,
            evaluationId: data.evaluationId,
            status: INITIAL_STATUS,
            configurationSnapshot: JSON.stringify(data.configuration.snapshot),
          },
        })

        return this.toStored(execution)
      })
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

  private async assertCurrent(tx: Prisma.TransactionClient, prepared: PreparedAgentConfiguration): Promise<void> {
    const current = await this.settings.prepare(prepared.agentType, tx)
    if (current.fingerprint !== prepared.fingerprint) throw new AgentConfigurationError([{ agentType: prepared.agentType, reason: "Configuration changed before starting; retry" }])
  }

  async complete(id: number, data: AgentExecutionCompletion): Promise<StoredAgentExecution> {
    const execution = await this.db.agentExecution.update({
      where: { id },
      data: {
        status: data.status,
        result: data.result,
        error: data.error,
        ...(data.inputTokens === null ? {} : { inputTokens: data.inputTokens }),
        ...(data.outputTokens === null ? {} : { outputTokens: data.outputTokens }),
        ...(data.estimatedTokens == null ? {} : { estimatedTokens: data.estimatedTokens }),
        ...(data.accountedTokens == null ? {} : { accountedTokens: data.accountedTokens }),
        ...(data.interruptionReason === undefined ? {} : { interruptionReason: data.interruptionReason }),
        finishedAt: new Date(),
      },
    })

    return this.toStored(execution)
  }

  /** Generic row creation shared by every pipeline: version row is saved (or
   *  reused), it becomes the selected one, a fresh evaluation is created, and
   *  one Waiting execution per configuration is stored with its snapshot. */
  async createExecutionsForProject(projectId: number, branch: string, commitHash: string, configurations: PreparedAgentConfiguration[]) {
    if (configurations.length === 0) throw new AgentConfigurationError([{ agentType: "pipeline", reason: "At least one stage configuration is required" }])
    return this.db.$transaction(async (tx) => {
      const running = await tx.agentExecution.findFirst({ where: {
        status: { in: ["Waiting", "Running"] }, evaluation: { projectVersion: { projectId, commitHash } },
      } })
      if (running) throw new UnknownExecutionTargetError(`Version ${commitHash.slice(0, 7)} is already being analyzed (execution ${running.id})`)
      for (const configuration of configurations) await this.assertCurrent(tx, configuration)
      const version = await tx.projectVersion.upsert({
        where: { projectId_commitHash: { projectId, commitHash } },
        create: { projectId, branch, commitHash, analysisStatus: "Pending" }, update: { branch },
      })
      await tx.project.update({ where: { id: projectId }, data: { selectedVersionId: version.id } })
      const evaluation = await tx.evaluation.create({ data: { projectVersionId: version.id, type: "Analysis" } })
      const executions: Record<string, StoredAgentExecution> = {}
      for (const configuration of configurations) {
        executions[configuration.agentType] = this.toStored(await tx.agentExecution.create({ data: {
          evaluationId: evaluation.id, agentType: configuration.agentType, status: INITIAL_STATUS,
          configurationSnapshot: JSON.stringify(configuration.snapshot),
        } }))
      }
      return { versionId: version.id, evaluationId: evaluation.id, executions }
    })
  }

  async markRunning(id: number): Promise<StoredAgentExecution> {
    const execution = await this.db.agentExecution.update({
      where: { id },
      data: { status: "Running", startedAt: new Date() },
    })

    return this.toStored(execution)
  }

  async patchResult(id: number, result: string): Promise<StoredAgentExecution> {
    const execution = await this.db.agentExecution.update({
      where: { id },
      data: { result },
    })

    return this.toStored(execution)
  }

  async updateUsage(id: number, usage: AgentExecutionUsage): Promise<StoredAgentExecution> {
    for (const value of Object.values(usage)) {
      if (value !== null && (!Number.isInteger(value) || value < 0 || value > 2147483647)) {
        throw new RangeError("Token usage must contain non-negative 32-bit integers or null provider counts")
      }
    }
    if (usage.accountedTokens !== (usage.inputTokens ?? 0) + (usage.outputTokens ?? 0) + usage.estimatedTokens) {
      throw new RangeError("Accounted tokens must equal reported input, reported output and estimated tokens")
    }
    // Atomic guard: duplicate/stale progress cannot reduce usage or reopen a run.
    await this.db.agentExecution.updateMany({
      where: {
        id, status: "Running",
        AND: [
          { OR: [{ accountedTokens: null }, { accountedTokens: { lte: usage.accountedTokens } }] },
          { OR: [{ inputTokens: null }, { inputTokens: { lte: usage.inputTokens ?? 0 } }] },
          { OR: [{ outputTokens: null }, { outputTokens: { lte: usage.outputTokens ?? 0 } }] },
        ],
      },
      data: usage,
    })
    return this.toStored(await this.db.agentExecution.findUniqueOrThrow({ where: { id } }))
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
    estimatedTokens: number | null
    accountedTokens: number | null
    interruptionReason: string | null
    createdAt: Date
    startedAt: Date | null
    finishedAt: Date | null
    configurationSnapshot?: string | null
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
      estimatedTokens: execution.estimatedTokens,
      accountedTokens: execution.accountedTokens,
      interruptionReason: execution.interruptionReason,
      createdAt: execution.createdAt,
      startedAt: execution.startedAt,
      finishedAt: execution.finishedAt,
      configuration: execution.configurationSnapshot ? JSON.parse(execution.configurationSnapshot) as AgentConfiguration : null,
    }
  }
}

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
  configuration?: AgentConfiguration | null
}

export interface AgentExecutionStore {
  create(data: NewAgentExecution): Promise<StoredAgentExecution>
  complete(id: number, data: AgentExecutionCompletion): Promise<StoredAgentExecution>
  markRunning(id: number): Promise<StoredAgentExecution>
  findById(id: number): Promise<StoredAgentExecution | null>
  createForProject(projectId: number, branch: string, commitHash: string, configuration: PreparedAgentConfiguration): Promise<{ versionId: number, evaluationId: number, execution: StoredAgentExecution }>
  createPipelineForProject(projectId: number, branch: string, commitHash: string, configurations: PreparedAgentConfiguration[]): Promise<{ versionId: number, evaluationId: number, execution: StoredAgentExecution, executions: { analyzer: StoredAgentExecution, architect: StoredAgentExecution } }>
  createPipeline(evaluationId: number, configurations: PreparedAgentConfiguration[]): Promise<{ analyzer: StoredAgentExecution, architect: StoredAgentExecution }>
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

  async createForProject(projectId: number, branch: string, commitHash: string, configuration: PreparedAgentConfiguration) {
    return this.db.$transaction(async (tx) => {
      await this.assertCurrent(tx, configuration)
      const running = await tx.agentExecution.findFirst({ where: {
        status: { in: ["Waiting", "Running"] }, evaluation: { projectVersion: { projectId, commitHash } },
      } })
      if (running) throw new UnknownExecutionTargetError(`Version ${commitHash.slice(0, 7)} is already being analyzed (execution ${running.id})`)
      const version = await tx.projectVersion.upsert({
        where: { projectId_commitHash: { projectId, commitHash } },
        create: { projectId, branch, commitHash, analysisStatus: "Pending" }, update: { branch },
      })
      await tx.project.update({ where: { id: projectId }, data: { selectedVersionId: version.id } })
      const evaluation = await tx.evaluation.create({ data: { projectVersionId: version.id, type: "Analysis" } })
      const execution = await tx.agentExecution.create({ data: {
        evaluationId: evaluation.id, agentType: configuration.agentType, status: INITIAL_STATUS,
        configurationSnapshot: JSON.stringify(configuration.snapshot),
      } })
      return { versionId: version.id, evaluationId: evaluation.id, execution: this.toStored(execution) }
    })
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

  async createPipelineForProject(projectId: number, branch: string, commitHash: string, configurations: PreparedAgentConfiguration[]) {
    return this.db.$transaction(async (tx) => {
      const running = await tx.agentExecution.findFirst({ where: {
        status: { in: ["Waiting", "Running"] }, evaluation: { projectVersion: { projectId, commitHash } },
      } })
      if (running) throw new UnknownExecutionTargetError(`Version ${commitHash.slice(0, 7)} is already being analyzed (execution ${running.id})`)
      const version = await tx.projectVersion.upsert({
        where: { projectId_commitHash: { projectId, commitHash } },
        create: { projectId, branch, commitHash, analysisStatus: "Pending" }, update: { branch },
      })
      await tx.project.update({ where: { id: projectId }, data: { selectedVersionId: version.id } })
      const evaluation = await tx.evaluation.create({ data: { projectVersionId: version.id, type: "Analysis" } })
      const executions = await this.createPipelineRows(tx, evaluation.id, configurations)
      return { versionId: version.id, evaluationId: evaluation.id, execution: executions.analyzer, executions }
    })
  }

  async createPipeline(evaluationId: number, configurations: PreparedAgentConfiguration[]) {
    return this.db.$transaction((tx) => this.createPipelineRows(tx, evaluationId, configurations))
  }

  private async createPipelineRows(tx: Prisma.TransactionClient, evaluationId: number, configurations: PreparedAgentConfiguration[]) {
    const analyzer = configurations.find((configuration) => configuration.agentType === "analyzer")
    const architect = configurations.find((configuration) => configuration.agentType === "architect")
    if (!analyzer || !architect) throw new AgentConfigurationError([{ agentType: "pipeline", reason: "Analyzer and architect configurations are required" }])
    for (const configuration of [analyzer, architect]) await this.assertCurrent(tx, configuration)
    const create = async (configuration: PreparedAgentConfiguration) => this.toStored(await tx.agentExecution.create({ data: {
      evaluationId, agentType: configuration.agentType, status: INITIAL_STATUS,
      configurationSnapshot: JSON.stringify(configuration.snapshot),
    } }))
    return { analyzer: await create(analyzer), architect: await create(architect) }
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
      createdAt: execution.createdAt,
      startedAt: execution.startedAt,
      finishedAt: execution.finishedAt,
      configuration: execution.configurationSnapshot ? JSON.parse(execution.configurationSnapshot) as AgentConfiguration : null,
    }
  }
}

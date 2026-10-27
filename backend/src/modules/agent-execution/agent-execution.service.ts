import { logger } from "../../config/logger.js"
import { auditRunConfiguration } from "../quality-audit/audit-run-configuration.js"
import type { AgentExecutionEvent } from "../../infrastructure/realtime-gateway/realtime.gateway.js"
import type { AgentInput, AgentInvoker, AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { AgentTransportError, AuditRunUnavailableError, QUALITY_AUDIT_INVOKE_TIMEOUT_MS } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { setTimeout as delay } from "node:timers/promises"
import type { AgentTargetResolver } from "../../infrastructure/agent-target/agent-target.resolver.js"
import { assertDirectCheckout, sanitizeDirectInput } from "../../infrastructure/agent-target/direct-input.guard.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import type { AgentRunConfig } from "../agent-settings/agent-configuration.js"
import type { ProjectArchitectureAnalysisRequest } from "../project/project.service.js"
import { MAINTAINABILITY_AGENT_TYPE, SECURITY_AGENT_TYPE, FUNCTIONAL_ADEQUACY_AGENT_TYPE, PROJECT_ARCHITECTURE_PIPELINE_NAME, PROJECT_ARCHITECTURE_PIPELINE_STAGES } from "../agent-settings/agent-types.js"
import { invocationEvents } from "./invocationReceipt.js"
import {
  INITIAL_STATUS,
  type AgentExecutionCompletion,
  type AgentExecutionUsage,
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

/** The rows one project-architecture pipeline drives, keyed by stage name. */
export interface ProjectArchitectureExecutions {
  orientation: StoredAgentExecution
  architecture: StoredAgentExecution
  semantic_validation: StoredAgentExecution
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

  async openQualityAudit(projectId: number, branch: string, commitHash: string, attributes: string[], options: AuditOperatingOptions = {}) {
    if (options.maintainability_selection !== undefined) {
      await this.settings.validateMaintainabilitySelection(options.maintainability_selection)
    }
    const agentType = attributes.includes("maintainability") ? MAINTAINABILITY_AGENT_TYPE
      : attributes.includes("security") ? SECURITY_AGENT_TYPE : FUNCTIONAL_ADEQUACY_AGENT_TYPE
    const configurations = await this.settings.prepareExecution([
      ...(attributes.includes("maintainability") ? [MAINTAINABILITY_AGENT_TYPE] : []),
      ...(attributes.includes("security") ? [SECURITY_AGENT_TYPE] : []),
      ...(attributes.includes("functional_adequacy") ? [FUNCTIONAL_ADEQUACY_AGENT_TYPE] : []),
    ])
    const rootConfiguration = configurations.find((item) => item.agentType === agentType)!
    const configs: Record<string, AgentRunConfig> = {}
    for (const configuration of configurations) {
      const participants = await this.settings.modelParticipants(configuration.agentType)
      for (const participant of participants) configs[participant] = configuration.transport
    }
    const scope = auditRunConfiguration(await this.settings.list(), branch, commitHash, attributes, options.maintainability_selection)
    const maintainability = scope.scopes.find((attribute) => attribute.id === "maintainability")
    const effectiveOptions = maintainability ? { ...options, maintainability_selection: Object.fromEntries(
      maintainability.subcharacteristics.map((child) => [child.id, child.investigators.map((agent) => agent.id)])) } : options
    if (effectiveOptions.maintainability_selection !== undefined) {
      await this.settings.validateMaintainabilitySelection(effectiveOptions.maintainability_selection)
    }
    const snapshot = { ...rootConfiguration.snapshot, auditConfiguration: scope }
    const result = await this.executions.createExecutionsForProject(projectId, branch, commitHash, [{ ...rootConfiguration, snapshot }], "QualityAudit")
    const execution = result.executions[agentType]!
    await this.executions.patchResult(execution.id, JSON.stringify({ attributes }))
    this.events.broadcast({ type: "agent-execution.opened", execution: toEvent(execution) })
    void this.dispatchQualityAudit(execution, configs, commitHash, attributes, effectiveOptions)
    return { versionId: result.versionId, evaluationId: result.evaluationId, executionId: execution.id }
  }

  private async dispatchQualityAudit(execution: StoredAgentExecution, configs: Record<string, AgentRunConfig>, commitHash: string, attributes: string[], options: AuditOperatingOptions) {
    const recoveryDeadline = Date.now() + QUALITY_AUDIT_INVOKE_TIMEOUT_MS
    try {
      if (execution.evaluationId === null || !this.agents.runPipelineByName) throw new Error("Quality-audit pipeline is unavailable")
      const input = await this.targets.resolve(execution.evaluationId)
      await this.markRunning(execution.id)
      const payload = await this.agents.runPipelineByName("quality-audit", {
        ...options,
        root_path: String(input.root_path), commit_hash: commitHash, attributes,
      }, { [execution.agentType]: execution.id }, configs)
      await this.closeAudit(execution.id, payload["audit"])
    } catch (error) {
      if (error instanceof AgentTransportError && error.outcomeUncertain) {
        try {
          await this.reconcileAudit(execution.id, attributes, recoveryDeadline)
        } catch (recoveryError) {
          await this.fail(execution.id, recoveryError instanceof Error ? recoveryError.message : "Audit outcome could not be confirmed", "audit_outcome_unconfirmed")
        }
        return
      }
      await this.fail(execution.id, error instanceof Error ? error.message : String(error))
    }
  }

  private async closeAudit(id: number, audit: AgentInput | undefined) {
    if (!audit || !audit["report"] || typeof audit["report"] !== "object" || typeof audit["docx_base64"] !== "string") {
      throw new Error("Quality-audit pipeline returned no report")
    }
    // Completion describes delivery, independently of the report's quality status.
    await this.close(id, {
      status: "Completed", result: JSON.stringify(audit), error: null,
      inputTokens: null, outputTokens: null,
      interruptionReason: audit["status"] === "completed" ? null : String(audit["status"]),
    })
  }

  private async reconcileAudit(id: number, attributes: string[], deadline: number) {
    this.log.info(`Execution ${id}: connection interrupted; confirming the existing audit without restarting it`)
    // At least one status lookup even if the HTTP deadline itself just expired.
    do {
      const current = await this.require(id)
      if (current.status === "Completed" || current.status === "Failed") return
      let runId = current.invocations?.[0]?.run_id
      try { runId = (JSON.parse(current.result ?? "{}") as { run_id?: string }).run_id ?? runId } catch { /* Retained receipts are the fallback. */ }
      if (runId && this.agents.getAuditResult) {
        try {
          const audit = await this.agents.getAuditResult(runId, attributes)
          if (audit) {
            await this.closeAudit(id, audit)
            return
          }
        } catch (error) {
          if (error instanceof AuditRunUnavailableError) {
            throw new Error("Audit outcome could not be recovered: the agent-server no longer retains the run; this does not confirm agent failure", { cause: error })
          }
          // A transient status/report retrieval failure must not close a live run.
          this.log.info(`Execution ${id}: audit reconciliation temporarily unavailable`)
        }
      }
      if (Date.now() >= deadline) break
      await delay(Math.min(5000, deadline - Date.now()), undefined, { ref: false })
    } while (Date.now() <= deadline)
    throw new Error("Audit outcome could not be confirmed before the recovery deadline; communication was interrupted, not a confirmed agent failure")
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

  /** Starts any registered pipeline by name and then gets out of the way.
   *  Never throws: a failure here fails every row, because no stage got far
   *  enough to report for itself.
   *
   *  The pipeline-level diagram (mermaid) is not a stage row: once the run
   *  returns it is merged into the finished architecture row, so the frontend
   *  can render it from the same result it already parses. */
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

      const payload = await this.agents.runPipelineByName(pipeline, { root_path: String(input.root_path) }, executionIds, configs)
      await this.attachDiagram(executions["architecture"], payload)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      for (const execution of Object.values(executions)) await this.fail(execution.id, message)
    }
  }

  /** Merges the pipeline-level rendered diagram into the finished
   *  architecture row. Never throws: a missing diagram only means the
   *  frontend falls back to the structured counts. */
  private async attachDiagram(architecture: StoredAgentExecution | undefined, payload: unknown): Promise<void> {
    try {
      if (architecture === undefined) return
      const diagram = (payload as { diagram?: unknown } | null)?.diagram
      if (typeof diagram !== "object" || diagram === null) return
      const diagramRecord = diagram as Record<string, unknown>
      const { mermaid, report_origin, report_hash } = diagramRecord
      if (typeof mermaid !== "string" || mermaid.trim() === "") return

      const current = await this.executions.findById(architecture.id)
      if (current === null || current.status !== "Completed" || current.result === null) return
      let record: Record<string, unknown>
      try {
        const parsed: unknown = JSON.parse(current.result)
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return
        record = parsed as Record<string, unknown>
      } catch {
        return
      }
      if (typeof record["architecture_diagram"] === "object" && record["architecture_diagram"] !== null) return

      const patched = await this.executions.patchResult(
        architecture.id,
        JSON.stringify({
          ...record,
          architecture_diagram: {
            mermaid,
            structure: diagramRecord["structure"],
            views: Array.isArray(diagramRecord["views"]) ? diagramRecord["views"] : [],
            legend: Array.isArray(diagramRecord["legend"]) ? diagramRecord["legend"] : [],
            deviation_notes: Array.isArray(diagramRecord["deviation_notes"]) ? diagramRecord["deviation_notes"] : [],
            limitations: Array.isArray(diagramRecord["limitations"]) ? diagramRecord["limitations"] : [],
            report_origin: typeof report_origin === "string" ? report_origin : "original",
            ...(typeof report_hash === "string" ? { report_hash } : {}),
          },
        }),
      )
      this.events.broadcast({ type: "agent-execution.updated", execution: toEvent(patched) })
    } catch (error) {
      this.log.error(`Could not attach the diagram to execution ${architecture?.id}: ${error}`)
    }
  }

  /** Marks an invocation as in flight. Optional: the agent-server may skip it. */
  async markRunning(id: number, runId?: string): Promise<StoredAgentExecution> {
    const existing = await this.require(id)
    if (existing.status === "Completed" || existing.status === "Failed") return existing

    return this.executions.markRunning(id, runId)
  }

  async updateUsage(id: number, usage: AgentExecutionUsage): Promise<StoredAgentExecution> {
    await this.require(id)
    return this.executions.updateUsage(id, usage)
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

  async recordInvocation(id: number, receipt: import("./invocationReceipt.js").InvocationReceipt): Promise<StoredAgentExecution> {
    await this.require(id)
    return this.executions.recordInvocation(id, receipt)
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
  private async fail(id: number, message: string, interruptionReason?: string): Promise<void> {
    this.log.error(`Execution ${id} failed: ${message}`)

    try {
      const retained = interruptionReason === "audit_outcome_unconfirmed" ? await this.require(id) : null
      await this.close(id, {
        status: "Failed",
        result: retained?.result ?? null,
        error: message.slice(0, 2000),
        inputTokens: null,
        outputTokens: null,
        ...(interruptionReason ? { interruptionReason } : {}),
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
    invocations: invocationEvents(execution.invocations),
    id: execution.id,
    evaluationId: execution.evaluationId,
    agentType: execution.agentType,
    status: execution.status,
    // Audit artifacts are retrieved through project-scoped report endpoints;
    // avoid broadcasting source inventories and binary base64 to every client.
    result: [MAINTAINABILITY_AGENT_TYPE, SECURITY_AGENT_TYPE, FUNCTIONAL_ADEQUACY_AGENT_TYPE].includes(execution.agentType) ? null : execution.result,
    error: execution.error,
    inputTokens: execution.inputTokens,
    outputTokens: execution.outputTokens,
    estimatedTokens: execution.estimatedTokens,
    interruptionReason: execution.interruptionReason,
    createdAt: execution.createdAt,
    startedAt: execution.startedAt,
    finishedAt: execution.finishedAt,
  }
}

export { INITIAL_STATUS }
export type { AgentExecutionStatus, AgentInput, StoredAgentExecution }

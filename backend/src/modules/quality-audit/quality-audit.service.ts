import { randomUUID } from "node:crypto"
import type { AgentExecutionService } from "../agent-execution/agent-execution.service.js"
import type { AuditSettingsService } from "./audit-settings.service.js"
import { AgentInvocationError, AgentTransportError, AuditRunUnavailableError, VERIFICATION_SUITE_INVOKE_TIMEOUT_MS, type AgentInvoker, type AuditOperatingOptions } from "../../infrastructure/agent-server-client/agent-server.client.js"
import { InvalidGitRequestError, ProjectFileError, ProjectNotFoundError, type ProjectService } from "../project/project.service.js"
import type { QualityAuditRepository } from "./quality-audit.repository.js"
import type { AuditRunConfiguration } from "./audit-run-configuration.js"
import type { InvocationReceipt } from "../agent-execution/invocationReceipt.js"
import { storedExecutionErrorDetail } from "../agent-execution/execution-error-detail.js"
import { publicErrorText, publicErrorFields } from "../../infrastructure/security/public-errors.js"
import { auditReportSections, type AuditReportSection } from "./audit-report-sections.js"
import { findingResolutionFindings } from "./finding-resolution.js"
import { AuditArtifactStore, parseArtifactManifest, type AuditArtifactManifest } from "./audit-artifacts.js"
import { projectAuditIssues, readAuditIssues } from "./audit-issues.js"
import type { AgentSettingsService } from "../agent-settings/agent-settings.service.js"
import { AgentConfigurationError } from "../agent-settings/agent-configuration.js"

export class AuditNotFoundError extends Error {}
export class AuditReportUnavailableError extends Error {}
export class AuditEvidenceUnavailableError extends Error {}
export class ArchitectureContextRequiredError extends Error {}
export class ArchitectureContextUnavailableError extends Error {}

type AuditRow = NonNullable<Awaited<ReturnType<QualityAuditRepository["find"]>>>
interface AuditArtifacts {
  run_id?: string
  attributes: string[]
  status: string
  report?: Record<string, unknown>
  docx_base64?: string
  artifacts?: unknown
}

function artifacts(row: AuditRow): AuditArtifacts | null {
  return row.result === null ? null : JSON.parse(row.result) as AuditArtifacts
}

function artifactManifest(row: AuditRow): AuditArtifactManifest | null {
  const result = artifacts(row)
  return result?.artifacts === undefined ? null : parseArtifactManifest(result.artifacts)
}

function reportRequired(row: AuditRow): AuditArtifacts | null {
  const result = artifacts(row)
  return result?.artifacts !== undefined && artifactManifest(row) !== null || result?.report ? result : null
}

function artifactRequired(row: AuditRow): AuditArtifacts | null {
  const result = artifacts(row)
  return result !== null && (artifactManifest(row) !== null || (result.report !== undefined && result.docx_base64 !== undefined)) ? result : null
}

type SummaryRow = Pick<AuditRow, "id" | "agentType" | "evaluationId" | "status" | "error" | "createdAt" | "startedAt" | "finishedAt" | "configurationSnapshot"> & {
  errorDetail?: string | null
  cancellationRequestedAt?: Date | null
  evaluation: { projectVersion: { branch: string | null, commitHash: string | null } } | null
}

function summary(row: SummaryRow, result: Partial<Pick<AuditArtifacts, "run_id" | "attributes" | "status">> | null, reportAvailable: boolean) {
  const configuration = savedConfiguration(row)
  return {
    id: row.id,
    runId: result?.run_id ?? null,
    evaluationId: row.evaluationId,
    branch: configuration?.branch ?? row.evaluation!.projectVersion.branch,
    commitHash: configuration?.commitHash ?? row.evaluation!.projectVersion.commitHash,
    attributes: configuration?.attributes ?? result?.attributes ?? [row.agentType === "maintainability_manager" ? "maintainability" : row.agentType],
    configurationAvailable: configuration !== null,
    executionStatus: row.status,
    auditStatus: row.cancellationRequestedAt && ["Waiting", "Running"].includes(row.status) ? "cancelling" : result?.status ?? null,
    cancellationRequestedAt: row.cancellationRequestedAt ?? null,
    error: publicErrorText(row.error),
    errorDetail: storedExecutionErrorDetail(row.errorDetail),
    createdAt: row.createdAt,
    startedAt: row.startedAt,
    finishedAt: row.finishedAt,
    reportAvailable,
  }
}

function savedConfiguration(row: { configurationSnapshot: string | null }): AuditRunConfiguration | null {
  try {
    const snapshot = JSON.parse(row.configurationSnapshot ?? "null") as { auditConfiguration?: AuditRunConfiguration } | null
    return snapshot?.auditConfiguration?.version === 1 ? snapshot.auditConfiguration : null
  } catch { return null }
}

export class QualityAuditService {
  private readonly artifactStore: AuditArtifactStore

  constructor(private repository: QualityAuditRepository, private projects: ProjectService, private executions: AgentExecutionService,
    private settings?: AuditSettingsService, private agents?: Pick<AgentInvoker, "getAuditSnapshot" | "requestVerificationSuite" | "downloadVerificationSuite" | "getVerificationSuite">,
    artifactStore?: AuditArtifactStore, private modelSettings?: Pick<AgentSettingsService, "prepareExecution">) {
    this.artifactStore = artifactStore ?? new AuditArtifactStore()
  }

  /** Verification-suite builds are multi-minute; they run in the background and
   *  are deduped per run so the UI can poll for a stable artifact. */
  private readonly suiteInFlight = new Map<string, Promise<void>>()
  private readonly suiteOutcomes = new Map<string, { status: "failed" | "recovering", message: string } | { status: "ready", summary: Record<string, unknown> }>()
  private readonly suiteAttempts = new Map<string, string>()
  private readonly suiteTargets = new Map<string, string | undefined>()
  private static suiteKey(runId: string, action: "create" | "execute", group?: string) { return `${runId}:${action}${group ? `:${group}` : ""}` }

  async cancel(projectId: number, id: number) {
    if (!await this.repository.findSummary(projectId, id)) throw new AuditNotFoundError("Audit not found for this project")
    await this.executions.cancelQualityAudit(id)
    return this.detail(projectId, id)
  }

  async start(projectId: number, branch: string, commitHash: string, attributes: string[], options: AuditOperatingOptions = {}) {
    if (options.request !== undefined) throw new InvalidGitRequestError("Maintainability input is loaded from the saved architecture context, not from the client")
    if (!attributes.length || new Set(attributes).size !== attributes.length
      || attributes.some((attribute) => !["maintainability", "security", "functional_adequacy"].includes(attribute))) {
      throw new InvalidGitRequestError("Select distinct supported quality attributes: maintainability, security, functional_adequacy")
    }
    const requirements = options.functional_requirements
    if (options.maintainability_selection !== undefined && !attributes.includes("maintainability")) {
      throw new InvalidGitRequestError("maintainability_selection requires maintainability in attributes")
    }
    if (attributes.includes("functional_adequacy")) {
      if (requirements !== undefined && (requirements.length > 100
        || requirements.some((item) => !item.requirement_id?.trim() || !item.description?.trim())
        || new Set(requirements.map((item) => item.requirement_id.trim())).size !== requirements.length)) {
        throw new InvalidGitRequestError("Functional requirements must have distinct IDs and nonempty descriptions (maximum 100)")
      }
    } else if (requirements !== undefined) {
      throw new InvalidGitRequestError("functional_requirements requires functional_adequacy in attributes")
    }
    if (options.security_config && !attributes.includes("security")) {
      throw new InvalidGitRequestError("security_config requires security in attributes")
    }
    if (options.call_limits && !attributes.includes("maintainability")) {
      throw new InvalidGitRequestError("call_limits requires maintainability; use security_config for security")
    }
    if (options.functional_config && !attributes.includes("functional_adequacy")) {
      throw new InvalidGitRequestError("functional_config requires functional_adequacy in attributes")
    }
    if (options.attribute_options && Object.keys(options.attribute_options).some((attribute) => !attributes.includes(attribute))) {
      throw new InvalidGitRequestError("attribute_options must belong to selected attributes")
    }
    if (!/^[a-fA-F0-9]{40}$/.test(commitHash)) throw new InvalidGitRequestError("Select a full commit hash")
    const { project, cleanBranch, cleanHash } = await this.projects.validateAnalysisTarget(projectId, branch, commitHash)
    const context = attributes.includes("maintainability") ? await this.repository.architectureContext(project.id, cleanHash) : null
    if (attributes.includes("maintainability") && !context) {
      throw new ArchitectureContextRequiredError("Run Analyze to generate architecture context for this project version before auditing maintainability")
    }
    const configured = this.settings ? await this.settings.executionOptions(attributes, options) : options
    const effective = context ? { ...configured, request: { documented_architecture: JSON.parse(context.result) as Record<string, unknown> } } : configured
    if (attributes.length === 1 && attributes[0] === "functional_adequacy" && !requirements?.length) {
      const result = await this.repository.createExploratoryFunctionalAudit(project.id, cleanBranch, cleanHash)
      await this.executions.dispatchExploratoryFunctionalAudit(result.executionId, cleanHash, effective)
      return result
    }
    return this.executions.openQualityAudit(project.id, cleanBranch, cleanHash, attributes, effective, context ? {
      executionId: context.executionId, projectVersionId: context.projectVersionId,
      schemaVersion: context.schemaVersion, executionStatus: context.executionStatus,
    } : undefined)
  }

  async architectureContext(projectId: number, commitHash: string) {
    if (!/^[a-fA-F0-9]{40}$/.test(commitHash)) throw new InvalidGitRequestError("Select a full commit hash")
    if (!await this.repository.projectExists(projectId)) throw new ProjectNotFoundError("Project not found")
    const context = await this.repository.architectureContext(projectId, commitHash.toLowerCase())
    return { projectId, commitHash: commitHash.toLowerCase(), available: context !== null,
      executionId: context?.executionId ?? null, executionStatus: context?.executionStatus ?? null }
  }

  async architectureContextContent(projectId: number, commitHash: string) {
    if (!/^[a-fA-F0-9]{40}$/.test(commitHash)) throw new InvalidGitRequestError("Select a full commit hash")
    if (!await this.repository.projectExists(projectId)) throw new ProjectNotFoundError("Project not found")
    const context = await this.repository.architectureContext(projectId, commitHash.toLowerCase())
    if (!context) throw new ArchitectureContextUnavailableError("Architecture context not available for this project version")
    return { projectId, commitHash: commitHash.toLowerCase(), executionId: context.executionId,
      executionStatus: context.executionStatus, schemaVersion: context.schemaVersion, createdAt: context.createdAt,
      data: JSON.parse(context.result) as Record<string, unknown> }
  }

  /** Standalone revalidation: it reuses the persisted audit findings but does
   *  not join the quality-audit pipeline or its callback contract. */
  async startFindingResolution(projectId: number, auditId: number, commitHash: string, findingIds?: string[]) {
    if (!/^[a-fA-F0-9]{40}$/.test(commitHash)) throw new InvalidGitRequestError("Select a full commit hash")
    const row = await this.repository.find(projectId, auditId)
    if (!row) throw new AuditNotFoundError("Audit not found for this project")
    const auditCommit = row.evaluation?.projectVersion.commitHash
    if (!auditCommit || auditCommit.toLowerCase() !== commitHash.toLowerCase()) {
      throw new InvalidGitRequestError("Finding resolution must target the audited commit")
    }
    if (!["Completed", "Failed"].includes(row.status)) {
      throw new AuditReportUnavailableError("The audit must finish before its findings can be revalidated")
    }
    if (findingIds !== undefined && (!findingIds.length || new Set(findingIds).size !== findingIds.length
      || findingIds.some((id) => typeof id !== "string" || id.trim() === ""))) {
      throw new InvalidGitRequestError("findingIds must be distinct nonempty identifiers")
    }
    const result = reportRequired(row)
    if (!result) throw new AuditReportUnavailableError("The audit report is not available yet")
    const manifest = artifactManifest(row)
    let findings
    if (manifest) {
      await this.artifactStore.assertAvailable(manifest)
      const section = await this.readReportSection(manifest, "quality_results")
      findings = findingResolutionFindings({ quality_results: section }, findingIds)
    } else {
      findings = findingResolutionFindings(result.report!, findingIds)
    }
    if (!findings.length) throw new InvalidGitRequestError("No findings are available to revalidate")
    return this.executions.openFindingResolution(projectId, row.evaluation?.projectVersion.branch ?? null,
      auditCommit.toLowerCase(), findings, auditId)
  }

  async list(projectId: number, pagination?: { limit: number, offset: number }) {
    if (!await this.repository.projectExists(projectId)) throw new ProjectNotFoundError("Project not found")
    const page = await this.repository.list(projectId, pagination?.limit, pagination?.offset)
    const items = page.items.map(({ row, projection }) => summary(row, {
      ...(projection.runId !== null ? { run_id: projection.runId } : {}),
      ...(projection.auditStatus !== null ? { status: projection.auditStatus } : {}),
      ...(projection.attributes ? { attributes: JSON.parse(projection.attributes) as string[] } : {}),
    }, projection.reportType === "object"))
    return pagination ? { ...page, items } : items
  }

  async detail(projectId: number, id: number) {
    const data = await this.repository.findSummary(projectId, id)
    if (!data) throw new AuditNotFoundError("Audit not found for this project")
    const { row, projection } = data
    return summary(row, { ...(projection.runId !== null ? { run_id: projection.runId } : {}),
      ...(projection.auditStatus !== null ? { status: projection.auditStatus } : {}),
      ...(projection.attributes ? { attributes: JSON.parse(projection.attributes) as string[] } : {}) }, projection.reportType === "object")
  }

  async executionIssues(projectId: number, id: number) {
    // Resolve the project-owned artifact before any filesystem access. Do not
    // call reportSection: its annexes include the entire evidence inventory.
    const row = await this.repository.find(projectId, id)
    if (!row) throw new AuditNotFoundError("Audit not found for this project")
    const manifest = artifactManifest(row)
    let issues: unknown
    if (manifest) {
      await this.artifactStore.assertAvailable(manifest)
      issues = await readAuditIssues(this.artifactStore.sectionPath(manifest, "annexes_and_traceability"))
    } else {
      const legacy = await this.repository.findReportSection(projectId, id, "annexes_and_traceability")
      if (legacy === null) throw new AuditNotFoundError("Audit not found for this project")
      if (legacy.reportType !== "object") throw new AuditReportUnavailableError("The audit report is not available yet")
      issues = (JSON.parse(legacy.data ?? "null") as { execution_issues?: unknown } | null)?.execution_issues
    }
    return { execution_issues: publicErrorFields(projectAuditIssues(issues)) }
  }

  async reportSection(projectId: number, id: number, section: string) {
    if (!auditReportSections.includes(section as AuditReportSection)) throw new InvalidGitRequestError("Unknown audit report section")
    const legacy = await this.repository.findReportSection(projectId, id, section as AuditReportSection)
    if (legacy?.reportType === "object") return { section, data: publicErrorFields(JSON.parse(legacy.data ?? "null")) }
    const artifact = await this.findArtifact(projectId, id)
    if (!artifact) throw legacy === null ? new AuditNotFoundError("Audit not found for this project") : new AuditReportUnavailableError("The audit report is not available yet")
    await this.artifactStore.assertAvailable(artifact.manifest)
    return { section, data: publicErrorFields(await this.readReportSection(artifact.manifest, section as AuditReportSection)) }
  }

  async report(projectId: number, id: number) {
    return publicErrorFields((await this.requireArtifacts(projectId, id)).report!)
  }

  async reportFile(projectId: number, id: number) {
    const artifact = await this.findArtifact(projectId, id)
    if (!artifact) return null
    await this.artifactStore.assertAvailable(artifact.manifest)
    return this.artifactStore.path(artifact.manifest, "report.json")
  }

  async documentFile(projectId: number, id: number) {
    const artifact = await this.findArtifact(projectId, id)
    if (!artifact) return null
    await this.artifactStore.assertAvailable(artifact.manifest)
    return this.artifactStore.path(artifact.manifest, "report.docx")
  }

  async verificationSuite(projectId: number, id: number, options: { action?: "create" | "execute", greenControl?: string, targetCommit?: string, group?: string } = {}) {
    const artifact = await this.findArtifact(projectId, id)
    if (!artifact) throw new AuditNotFoundError("Audit not found for this project")
    const runId = artifact.manifest.run_id
    if (!runId) throw new AuditReportUnavailableError("The audit run is not recorded yet")
    const requestVerificationSuite = this.agents?.requestVerificationSuite?.bind(this.agents)
    if (!requestVerificationSuite) {
      throw new AuditReportUnavailableError("Verification suite generation is not configured in this deployment")
    }
    const action = options.action ?? "create"
    if (options.targetCommit && (action !== "execute" || !/^[a-f0-9]{40}$/i.test(options.targetCommit))) {
      throw new InvalidGitRequestError("targetCommit must be a full Git hash and is only valid for execution")
    }
    const group = options.group?.toLowerCase()
    if (group !== undefined && !/^[a-z0-9_-]{1,32}$/.test(group)) {
      throw new InvalidGitRequestError("group must be a short identifier matching [A-Za-z0-9_-]{1,32}")
    }
    if (group !== undefined && action !== "execute") {
      throw new InvalidGitRequestError("group is only valid for action=execute")
    }
    const key = QualityAuditService.suiteKey(runId, action, action === "execute" ? options.group?.toLowerCase() : undefined)
    const targetCommit = options.targetCommit?.toLowerCase()
    if ((this.suiteInFlight.has(key) || this.suiteOutcomes.get(key)?.status === "recovering")
      && this.suiteTargets.get(key) !== targetCommit) {
      throw new InvalidGitRequestError("Another verification target is still running; wait for its result before changing commits")
    }
    if (this.suiteOutcomes.get(key)?.status === "recovering") {
      return { status: "recovering", run_id: runId, action }
    }
    // Only generation needs provider access; never use development credentials.
    let config
    let generation: import("../agent-execution/agent-execution.repository.js").StoredAgentExecution | null = null
    if (action === "create" && !this.suiteInFlight.has(key)) {
      if (!this.modelSettings) throw new AgentConfigurationError([{ agentType: "verification_suite", reason: "Configure the Verification Suite model and credential in Settings" }])
      const [prepared] = await this.modelSettings.prepareExecution(["verification_suite"])
      config = prepared!.transport
      if (artifact.row.evaluation?.projectVersionId !== undefined) {
        generation = await this.executions.openVerificationSuiteGeneration(artifact.row.evaluation.projectVersionId)
      }
    }
    // Access verification may yield to another request for this same run.
    if (!this.suiteInFlight.has(key)) {
      this.suiteOutcomes.delete(key)
      const attemptId = randomUUID()
      this.suiteAttempts.set(key, attemptId)
      this.suiteTargets.set(key, targetCommit)
      const promise = (async () => {
        try {
          const summary = await requestVerificationSuite(runId, { llm: "provider", config, allowExecution: true, timeoutMs: VERIFICATION_SUITE_INVOKE_TIMEOUT_MS, action, greenControl: options.greenControl, attemptId, targetCommit: options.targetCommit?.toLowerCase(), group, executionId: generation?.id })
          this.suiteOutcomes.set(key, { status: "ready", summary })
        } catch (error) {
          if (generation) await this.executions.closeVerificationSuiteGenerationAsFailed(generation.id)
          this.suiteOutcomes.set(key, {
            status: (error instanceof AgentTransportError && error.outcomeUncertain) || error instanceof TypeError || (error instanceof Error && ["TimeoutError", "AbortError"].includes(error.name)) ? "recovering" : "failed",
            message: error instanceof AgentInvocationError ? error.message : "Verification suite generation failed; check the agent-server diagnostics.",
          })
        } finally {
          this.suiteInFlight.delete(key)
        }
      })()
      this.suiteInFlight.set(key, promise)
    }
    return { status: "building", run_id: runId, action }
  }

  async verificationCommits(projectId: number, id: number, limit = 30, offset = 0) {
    const audit = await this.detail(projectId, id)
    if (!audit.commitHash || !audit.branch) throw new InvalidGitRequestError("The audit baseline or branch is unavailable")
    return this.projects.verificationCommits(projectId, audit.commitHash, audit.branch, limit, offset)
  }

  async verificationSuiteStatus(projectId: number, id: number, action: "create" | "execute" = "create", group?: string) {
    const artifact = await this.findArtifact(projectId, id)
    if (!artifact) throw new AuditNotFoundError("Audit not found for this project")
    const runId = artifact.manifest.run_id
    if (!runId) throw new AuditReportUnavailableError("The audit run is not recorded yet")
    const key = QualityAuditService.suiteKey(runId, action, action === "execute" ? group?.toLowerCase() : undefined)
    const outcome = this.suiteOutcomes.get(key)
    const attemptId = this.suiteAttempts.get(key)
    // Primary source: the artifact on disk — reading the state never blocks on a busy agent-server.
    const diskSummary = await this.artifactStore.verificationSuiteSummary(artifact.manifest)
    if (diskSummary) {
      const persistedAction = typeof diskSummary.action === "string" ? diskSummary.action : "create"
      if (persistedAction === action && (!attemptId || diskSummary.attempt_id === attemptId)) {
        this.suiteOutcomes.set(key, { status: "ready", summary: diskSummary })
        return { ...diskSummary, status: "ready", action }
      }
    }
    if (outcome?.status === "ready") return { ...outcome.summary, status: "ready", run_id: runId, action }
    if (this.suiteInFlight.has(key)) return { status: "building", run_id: runId, action }
    if (outcome?.status === "failed") return { status: "failed", run_id: runId, action, message: outcome.message }
    if (!this.agents?.getVerificationSuite) return { status: outcome?.status === "recovering" ? "recovering" : "not_built", run_id: runId, action }
    try {
      const summary = await this.agents.getVerificationSuite(runId)
      if (!summary) return { status: outcome?.status === "recovering" ? "recovering" : "not_built", run_id: runId, action }
      const agentAction = typeof summary.action === "string" ? summary.action : null
      if ((agentAction !== null && agentAction !== action) || (attemptId && summary.attempt_id !== attemptId)) return { status: outcome?.status === "recovering" ? "recovering" : "not_built", run_id: runId, action }
      this.suiteOutcomes.set(key, { status: "ready", summary })
      return { ...summary, status: "ready", action }
    } catch {
      return { status: "recovering", run_id: runId, action, message: "Waiting to reconnect to the agent server; the operation may still be running." }
    }
  }

  async verificationSuiteZip(projectId: number, id: number) {
    const artifact = await this.findArtifact(projectId, id)
    if (!artifact) return null
    const runId = artifact.manifest.run_id
    if (!runId) return null
    if (!this.agents?.downloadVerificationSuite) return null
    const response = await this.agents.downloadVerificationSuite(runId)
    return Buffer.from(await response.arrayBuffer())
  }

  async file(projectId: number, id: number, path: string) {
    // Scope and revision come from the persisted audit, never from client input.
    const audit = await this.detail(projectId, id)
    if (!audit.commitHash) throw new ProjectFileError("The audit has no recorded commit")
    return this.projects.readFileAtCommit(projectId, path, audit.commitHash)
  }

  async evidence(projectId: number, id: number) {
    // Project scope is checked before any remote read; no artifacts are materialized.
    const context = await this.repository.findSummary(projectId, id)
    if (!context) throw new AuditNotFoundError("Audit not found for this project")
    const partial = ["Waiting", "Running"].includes(context.row.status)
    if (!partial && context.projection.reportType === "object") {
      const section = await this.reportSection(projectId, id, "annexes_and_traceability")
      return { partial: false, available: section.data !== null, data: section.data }
    }
    const receipts = await this.repository.findConfiguration(projectId, id)
    const invocations = JSON.parse(receipts?.invocationReceipts ?? "[]") as InvocationReceipt[]
    const runId = context.projection.runId ?? invocations[0]?.run_id
    const unavailable = { partial, available: false, data: null }
    if (!runId || !this.agents?.getAuditSnapshot) return unavailable
    try {
      const snapshot = await this.agents.getAuditSnapshot(runId)
      if (snapshot.run_id !== runId) throw new Error("Unexpected audit identity")
      // Do not proxy the full Blackboard: it contains findings, nested reports and details.
      const inventory = Array.isArray(snapshot.evidence) ? snapshot.evidence : null
      const evidence = (inventory ?? []).flatMap((value) => {
        if (!value || typeof value !== "object" || Array.isArray(value)) return []
        const item = value as Record<string, unknown>
        if (item.run_id !== runId || typeof item.id !== "string" || typeof item.agent_id !== "string" || typeof item.invocation_id !== "string") return []
        return [{ id: item.id, kind: item.kind, source: item.source, content: item.content,
          start_line: item.start_line, end_line: item.end_line, commit: item.commit, tool_call_id: item.tool_call_id,
          provenance: { agent_id: item.agent_id, invocation_id: item.invocation_id } }]
      })
      return { partial, available: inventory !== null, data: { evidence_inventory: evidence,
        executions: invocations.map((item) => ({ agent_id: item.agent_id, invocation_id: item.invocation_id })) } }
    } catch (error) {
      if (error instanceof AuditRunUnavailableError) return unavailable
      throw new AuditEvidenceUnavailableError("Published audit evidence is temporarily unavailable")
    }
  }

  async configuration(projectId: number, id: number) {
    const row = await this.repository.findConfiguration(projectId, id)
    if (!row) throw new AuditNotFoundError("Audit not found for this project")
    const receipts = JSON.parse(row.invocationReceipts) as InvocationReceipt[]
    return { configuration: savedConfiguration(row), invocations: receipts.map((receipt) => ({
      id: receipt.invocation_id, agentId: receipt.agent_id, status: receipt.status,
    })) }
  }

  async document(projectId: number, id: number) {
    return Buffer.from((await this.requireArtifacts(projectId, id)).docx_base64, "base64")
  }

  private async findArtifact(projectId: number, id: number) {
    const row = await this.repository.find(projectId, id)
    if (!row) return null
    const result = artifacts(row)
    const manifest = artifactManifest(row)
    return manifest === null ? null : { row, result: result!, manifest }
  }

  private async readReportSection(manifest: AuditArtifactManifest, section: AuditReportSection): Promise<unknown> {
    return await this.artifactStore.readSection(manifest, section)
  }

  private async requireArtifacts(projectId: number, id: number) {
    const row = await this.repository.find(projectId, id)
    if (!row) throw new AuditNotFoundError("Audit not found for this project")
    const result = artifactRequired(row)
    if (!result?.report || !result.docx_base64) throw new AuditReportUnavailableError("The audit report is not available yet")
    return result as typeof result & { report: Record<string, unknown>, docx_base64: string }
  }
}

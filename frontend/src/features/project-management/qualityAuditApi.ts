import { ApiError, backendHttpUrl, requestJson, type ExecutionErrorDetail } from "../../infrastructure/http-client/httpClient.ts"
import type { AuditReportSection } from "./qualityAuditReport.ts"

export interface QualityAuditSummary {
  errorDetail?: ExecutionErrorDetail | null
  cancellationRequestedAt?: string | null
  id: number
  runId?: string | null
  evaluationId: number
  branch: string | null
  commitHash: string | null
  attributes: string[]
  executionStatus: string
  auditStatus: string | null
  error: string | null
  createdAt: string
  startedAt?: string | null
  finishedAt: string | null
  reportAvailable: boolean
  configurationAvailable?: boolean
}

export interface AuditParticipant { id: string, name: string }
export interface AuditAttributeScope {
  id: string
  requiredAgents: AuditParticipant[]
  subcharacteristics: { id: string, name: string, investigators: AuditParticipant[] }[]
  techniques: AuditParticipant[]
  investigators: AuditParticipant[]
}
export interface AuditRunConfiguration {
  version: 1
  branch: string
  commitHash: string
  attributes: string[]
  scopes: AuditAttributeScope[]
  architectureContext?: { executionId: number; projectVersionId: number; schemaVersion: string; executionStatus: string }
}
export interface AuditConfigurationHistory {
  configuration: AuditRunConfiguration | null
  invocations: { id: string, agentId: string, status: string }[]
}

export function getQualityAuditConfiguration(projectId: number, id: number, signal?: AbortSignal) {
  return requestJson<AuditConfigurationHistory>(`/api/projects/${projectId}/audits/${id}/configuration`, "Could not load audit configuration", { signal })
}

export function listQualityAudits(projectId: number, signal?: AbortSignal) {
  return requestJson<QualityAuditSummary[]>(`/api/projects/${projectId}/audits`, "Could not load the audit", { signal })
}

export interface QualityAuditPage {
  items: QualityAuditSummary[]
  total: number
  hasRunning: boolean
  limit: number
  offset: number
}

export function listQualityAuditPage(projectId: number, limit: number, offset: number, signal?: AbortSignal) {
  return requestJson<QualityAuditPage>(`/api/projects/${projectId}/audits?limit=${limit}&offset=${offset}`, "Could not load audits", { signal })
}

export function getQualityAudit(projectId: number, id: number, signal?: AbortSignal) {
  return requestJson<QualityAuditSummary>(`/api/projects/${projectId}/audits/${id}`, "Could not load the audit", { signal })
}

export function getQualityAuditReportSection(projectId: number, id: number, section: AuditReportSection, signal?: AbortSignal) {
  return requestJson<{ section: AuditReportSection, data: unknown }>(`/api/projects/${projectId}/audits/${id}/report/sections/${section}`, "Could not load report section", { signal })
}

export interface PublishedAuditEvidence { partial: boolean, available: boolean, data: unknown }
export function getPublishedAuditEvidence(projectId: number, id: number, signal?: AbortSignal) {
  return requestJson<PublishedAuditEvidence>(`/api/projects/${projectId}/audits/${id}/evidence`, "Could not load published evidence", { signal })
}

export interface AuditSourceFile { path: string, content: string, size: number, commitHash: string }
export function readAuditSourceFile(projectId: number, auditId: number, path: string, signal?: AbortSignal) {
  return requestJson<AuditSourceFile>(`/api/projects/${projectId}/audits/${auditId}/file`, "Could not read the audited source file", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }), signal,
  })
}

/** Optional audit scope and operating patches, validated by the server. */
export interface AuditOperatingOptions {
  maintainability_selection?: Record<string, string[]>
  functional_requirements?: { requirement_id: string, description: string }[]
  agent_defaults?: Record<string, unknown>
  security_config?: Record<string, unknown>
  functional_config?: Record<string, unknown>
  attribute_options?: Record<string, Record<string, unknown>>
  audit_budget?: Record<string, unknown>
  call_limits?: Record<string, unknown>
}

export function startQualityAudit(projectId: number, branch: string, commitHash: string, attributes: string[], options: AuditOperatingOptions = {}) {
  return requestJson<{ executionId: number }>(`/api/projects/${projectId}/audits`, "Could not load the audit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...options, branch, commitHash, attributes }),
  })
}

export interface FindingResolutionExecution {
  id: number
  agentType: string
  status: string
}

/** Starts the standalone finding_resolution agent for the audited commit. */
export function startFindingResolution(projectId: number, auditId: number, commitHash: string) {
  return requestJson<FindingResolutionExecution>(`/api/projects/${projectId}/audits/${auditId}/finding-resolution`, "Could not start the finding revalidation", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ commitHash }),
  })
}

export function getQualityAuditReport(projectId: number, id: number, signal?: AbortSignal) {
  return requestJson<Record<string, unknown>>(`/api/projects/${projectId}/audits/${id}/report`, "Could not load the audit", { signal })
}

export interface AuditFindingsExport {
  auditId: number
  commitHash: string | null
  attributes: string[]
  exportedAt: string
  findings: unknown[]
}

/** Extracts the findings list from a quality_results section payload, whatever its shape. */
export function findingsFromQualityResults(data: unknown): unknown[] {
  return data && typeof data === "object" && !Array.isArray(data) && Array.isArray((data as Record<string, unknown>).findings)
    ? (data as Record<string, unknown>).findings as unknown[] : []
}

/** Downloads the persisted findings list as a self-describing JSON envelope. */
export async function downloadQualityAuditFindings(id: number, audit: Pick<QualityAuditSummary, "commitHash" | "attributes">, findings: unknown[]) {
  const payload: AuditFindingsExport = {
    auditId: id,
    commitHash: audit.commitHash,
    attributes: audit.attributes,
    exportedAt: new Date().toISOString(),
    findings,
  }
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }))
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = `hallazgos-auditoria-${id}.json`
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function downloadQualityAuditReport(projectId: number, id: number) {
  const response = await fetch(`${backendHttpUrl()}/api/projects/${projectId}/audits/${id}/report.docx`)
  if (!response.ok) throw new ApiError(response.status, "Could not download the audit report", "client")
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = `informe-auditoria-${id}.docx`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export interface VerificationEntry { verification_id: string, rule_id: string | null, strategy: string, covered_property: string, status: string, generation_status?: string, summary?: string, generated_by?: string | null, green_status?: string, validated_red_green?: boolean, target_components?: string[], group?: string, generator?: string }

export interface VerificationSuitePage {
  ok: boolean
  run_id: string
  termination_reason: string
  zip_path: string | null
  verifications: VerificationEntry[]
  validation_status: string
  limitations: string[]
  action?: SuiteAction | null
  attempt_id?: string | null
  suite_id?: string | null
  suite_sha256?: string | null
  baseline_commit?: string | null
  target_commit?: string | null
  checkout_commit?: string | null
  groups?: { name: string, count: number }[]
  generators?: string[]
  selection?: string[]
}

export type SuiteAction = "create" | "execute"
export interface VerificationCommitEntry { commitHash: string, subject: string }
export interface VerificationCommitPage { commits: VerificationCommitEntry[], hasMore: boolean, baselineCommit: string, branch: string, branchTip: string, limit: number, offset: number }

export function listVerificationCommits(projectId: number, auditId: number, limit = 30, offset = 0): Promise<VerificationCommitPage> {
  return requestJson<VerificationCommitPage>(`/api/projects/${projectId}/audits/${auditId}/verification-commits?limit=${limit}&offset=${offset}`, "Could not load commits after the audited baseline", {
    signal: AbortSignal.timeout(15_000),
  })
}

export interface VerificationSuiteReady extends VerificationSuitePage { status: "ready" }
export interface VerificationSuiteTransient { status: "not_built" | "building" | "recovering" | "failed", run_id?: string, action?: SuiteAction, message?: string }
export type VerificationSuitePoll = VerificationSuiteReady | VerificationSuiteTransient

export function requestVerificationSuite(projectId: number, auditId: number, options: { action?: SuiteAction, greenControl?: string, targetCommit?: string, group?: string } = {}): Promise<VerificationSuitePoll> {
  // The build runs in the background on the backend; this returns status=building as soon as the run is registered.
  return requestJson<VerificationSuitePoll>(`/api/projects/${projectId}/audits/${auditId}/verification-suite`, "Could not request the verification suite", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: options.action ?? "create", greenControl: options.greenControl, targetCommit: options.targetCommit, group: options.group }),
  })
}

export function getVerificationSuite(projectId: number, auditId: number, action: SuiteAction = "create", group?: string): Promise<VerificationSuitePoll> {
  const suffix = group ? `&group=${encodeURIComponent(group)}` : ""
  return requestJson<VerificationSuitePoll>(`/api/projects/${projectId}/audits/${auditId}/verification-suite?action=${action}${suffix}`, "Could not read the verification suite status", {
    signal: AbortSignal.timeout(15_000),
  })
}

export async function downloadVerificationSuite(projectId: number, auditId: number) {
  const response = await fetch(`${backendHttpUrl()}/api/projects/${projectId}/audits/${auditId}/verification-suite.zip`)
  if (!response.ok) throw new ApiError(response.status, "Could not download the verification suite", "client")
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = `verification-suite-${auditId}.zip`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}


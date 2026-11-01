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

export function getQualityAuditReport(projectId: number, id: number, signal?: AbortSignal) {
  return requestJson<Record<string, unknown>>(`/api/projects/${projectId}/audits/${id}/report`, "Could not load the audit", { signal })
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

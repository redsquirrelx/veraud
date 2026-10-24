import { ApiError, backendHttpUrl, requestJson } from "../../infrastructure/http-client/httpClient.ts"

export interface QualityAuditSummary {
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
  finishedAt: string | null
  reportAvailable: boolean
}

export function listQualityAudits(projectId: number) {
  return requestJson<QualityAuditSummary[]>(`/api/projects/${projectId}/audits`, "Could not load the audit")
}

/** Optional operating patches; schemas and numeric bounds are owned by agent-server. */
export interface AuditOperatingOptions {
  functional_requirements?: { requirement_id: string, description: string }[]
  agent_defaults?: Record<string, unknown>
  security_config?: Record<string, unknown>
  audit_budget?: Record<string, unknown>
  call_limits?: Record<string, unknown>
}

export function startQualityAudit(projectId: number, branch: string, commitHash: string, attributes: string[], options: AuditOperatingOptions = {}) {
  return requestJson<{ executionId: number }>(`/api/projects/${projectId}/audits`, "Could not load the audit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...options, branch, commitHash, attributes }),
  })
}

export function getQualityAuditReport(projectId: number, id: number) {
  return requestJson<Record<string, unknown>>(`/api/projects/${projectId}/audits/${id}/report`, "Could not load the audit")
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

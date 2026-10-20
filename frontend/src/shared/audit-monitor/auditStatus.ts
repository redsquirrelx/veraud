import type { ParseKeys, TFunction } from "i18next"
import { formatNumber } from "../i18n/format.ts"

/** Lifecycle of an audit, of one of its pipelines, or of a single agent run. */
export type AuditRunState = "waiting" | "running" | "completed" | "partial" | "failed" | "unknown"

export interface AuditAgentRun {
  id: number | string
  /** Backend identifier, rendered verbatim: it is an agent type, not UI copy. */
  agentType: string
  state: AuditRunState
  inputTokens: number | null
  outputTokens: number | null
  startedAt: string | null
  finishedAt: string | null
  error: string | null
}

/** One quality attribute (maintainability, security, …) inside the audit. */
export interface AuditPipelineRun {
  id: string
  state: AuditRunState
  agents: AuditAgentRun[]
}

/** The repository this audit belongs to, enough to name and link it. */
export interface AuditProjectRef {
  id: number
  repositoryOwner: string
  repositoryName: string
}

export interface AuditStatusModel {
  id: number
  project: AuditProjectRef | null
  branch: string | null
  commitHash: string | null
  state: AuditRunState
  error: string | null
  createdAt: string
  finishedAt: string | null
  reportAvailable: boolean
  pipelines: AuditPipelineRun[]
}

export interface AuditProgress {
  finished: number
  total: number
}

/** Evaluation outcome wins over execution completion. Missing or unsupported
 * states remain explicitly unknown rather than claiming success or queueing. */
export function auditStateFrom(executionStatus: string, auditStatus: string | null): AuditRunState {
  if (auditStatus === "partial") {
    return "partial"
  }
  if (auditStatus === "failed") return "failed"
  if (auditStatus === "not_evaluated") return "unknown"
  if (auditStatus === "completed") return "completed"
  if (executionStatus === "Completed" || executionStatus === "completed") {
    return "completed"
  }
  if (executionStatus === "Failed" || executionStatus === "failed") {
    return "failed"
  }
  if (executionStatus === "partial") return "partial"
  if (executionStatus === "Running" || executionStatus === "running") {
    return "running"
  }
  return executionStatus === "Waiting" || executionStatus === "waiting" ? "waiting" : "unknown"
}

export function isFinished(state: AuditRunState): boolean {
  return state === "completed" || state === "partial" || state === "failed"
}

export function stateTone(state: AuditRunState): "success" | "warning" | "info" | "neutral" {
  if (state === "completed") {
    return "success"
  }
  if (state === "running") {
    return "info"
  }
  if (state === "partial" || state === "failed") {
    return "warning"
  }
  return "neutral"
}

const stateLabelKeys: Record<AuditRunState, ParseKeys<"projects">> = {
  waiting: "auditStatus.states.waiting",
  running: "auditStatus.states.running",
  completed: "auditStatus.states.completed",
  partial: "auditStatus.states.partial",
  failed: "auditStatus.states.failed",
  unknown: "auditStatus.agents.notReported",
}

export function stateLabelKey(state: AuditRunState): ParseKeys<"projects"> {
  return stateLabelKeys[state]
}

const pipelineLabelKeys: Record<string, ParseKeys<"projects">> = {
  maintainability: "auditStatus.pipelines.maintainability",
  security: "auditStatus.pipelines.security",
}

/** Translation key for a quality attribute, or null when the backend sends an
 *  attribute without a known label (rendered verbatim). */
export function pipelineLabelKey(id: string): ParseKeys<"projects"> | null {
  return pipelineLabelKeys[id] ?? null
}

export function pipelineProgress(pipeline: AuditPipelineRun): AuditProgress {
  return {
    finished: pipeline.agents.filter((agent) => isFinished(agent.state)).length,
    total: pipeline.agents.length,
  }
}

/** Agent counts across every pipeline, so the header reflects the whole audit. */
export function auditProgress(audit: AuditStatusModel): AuditProgress {
  return audit.pipelines.reduce<AuditProgress>((progress, pipeline) => {
    const counted = pipelineProgress(pipeline)
    return {
      finished: progress.finished + counted.finished,
      total: progress.total + counted.total,
    }
  }, { finished: 0, total: 0 })
}

/** One wording for agent counts, shared by the visible progress and by every
 *  summary that repeats it, so the two can never disagree. */
export function progressText(t: TFunction<"projects">, progress: AuditProgress): string {
  return progress.total === 0
    ? t("auditStatus.progress.empty")
    : t("auditStatus.progress.finished", { finished: formatNumber(progress.finished), total: formatNumber(progress.total) })
}

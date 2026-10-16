import type { ParseKeys } from "i18next"

export function statusTone(status: string): "success" | "warning" | "info" {
  if (status === "READY") {
    return "success"
  }
  if (status === "SYNCING") {
    return "info"
  }
  return "warning"
}

const projectBadgeLabelKeys: Record<string, ParseKeys<"projects">> = {
  QUEUED: "status.projectBadge.queued",
  READY: "status.projectBadge.ready",
  SYNCING: "status.projectBadge.syncing",
}

/** Translation key for a project status badge, or null when the backend
 *  sends a status without a known label (rendered verbatim). */
export function projectStatusLabelKey(status: string): ParseKeys<"projects"> | null {
  return projectBadgeLabelKeys[status] ?? null
}

export const executionStatusLabelKeys: Record<string, ParseKeys<"projects">> = {
  Waiting: "status.execution.waiting",
  Running: "status.execution.running",
  Completed: "status.execution.completed",
  Failed: "status.execution.failed",
}

export const completionStatusLabelKeys: Record<string, ParseKeys<"projects">> = {
  complete: "status.completion.complete",
  partial: "status.completion.partial",
  failed: "status.completion.failed",
}

export const claimStatusLabelKeys: Record<string, ParseKeys<"projects">> = {
  supported: "status.claim.supported",
  hypothesis: "status.claim.hypothesis",
  unresolved: "status.claim.unresolved",
}

export const reviewVerdictLabelKeys: Record<string, ParseKeys<"projects">> = {
  accepted: "status.review.accepted",
  revisions_needed: "status.review.revisionsNeeded",
  needs_evidence: "status.review.needsEvidence",
  inconclusive: "status.review.inconclusive",
}

export const findingVerdictLabelKeys: Record<string, ParseKeys<"projects">> = {
  supported: "status.finding.supported",
  overstated: "status.finding.overstated",
  contradicted: "status.finding.contradicted",
  insufficient_evidence: "status.finding.insufficientEvidence",
}

export const derivedStatusLabelKeys: Record<string, ParseKeys<"projects">> = {
  Completed: "status.derived.completed",
  Waiting: "status.derived.waiting",
  NeverAnalyzed: "status.derived.neverAnalyzed",
}

export const architectLegendLabelKeys: Record<string, ParseKeys<"projects">> = {
  Supported: "status.legendArchitect.supported",
  Hypothesis: "status.legendArchitect.hypothesis",
  Unresolved: "status.legendArchitect.unresolved",
}

export const semanticLegendLabelKeys: Record<string, ParseKeys<"projects">> = {
  Supported: "status.legendSemantic.supported",
  Overstated: "status.legendSemantic.overstated",
  Contradicted: "status.legendSemantic.contradicted",
  "Insufficient evidence": "status.legendSemantic.insufficientEvidence",
  "Not reviewed": "status.legendSemantic.notReviewed",
}

/** Translation key for a value in a status map, or null when the backend
 *  sends a value without a known label (rendered verbatim). */
export function statusLabelKey(keys: Record<string, ParseKeys<"projects">>, status: string): ParseKeys<"projects"> | null {
  return keys[status] ?? null
}

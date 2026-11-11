/** Adapter from the persisted audit report to the finding-resolution agent contract. */

type RecordValue = Record<string, unknown>
const object = (value: unknown): RecordValue => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as RecordValue : {}
const text = (value: unknown, fallback = ""): string => typeof value === "string" ? value : fallback
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : []

const SEVERITIES = new Set(["info", "low", "medium", "high", "critical"])
const ORIGINS = new Set(["explicit", "inferred", "design_principle"])

function criterion(value: unknown): RecordValue {
  const record = object(value)
  const id = text(record.id, "unspecified")
  return {
    id,
    description: text(record.description, id),
    origin: ORIGINS.has(text(record.origin)) ? text(record.origin) : "inferred",
    provenance: text(record.provenance, "Persisted audit report"),
  }
}

function validationStatus(verification: unknown): "accepted" | "rejected" | "insufficient_evidence" {
  if (verification === "verified") return "accepted"
  if (verification === "discarded") return "rejected"
  return "insufficient_evidence"
}

function confidence(technicalDetails: unknown): number {
  const value = object(technicalDetails).confidence
  return typeof value === "number" && value >= 0 && value <= 1 ? value : 0.5
}

/** Report findings are the persisted record of the audit; evidence bodies stay
 *  in the report and are not forwarded as current proof. The agent re-inspects
 *  the checkout and treats historical IDs as leads only. */
export function findingResolutionFindings(report: RecordValue, findingIds?: string[]): RecordValue[] {
  const quality = object(report.quality_results)
  const selected = findingIds === undefined ? null : new Set(findingIds)
  return list(quality.findings).flatMap((value) => {
    const record = object(value)
    const id = text(record.id)
    if (!id || (selected !== null && !selected.has(id))) return []
    const components = list(record.components).filter((item): item is string => typeof item === "string" && item.trim() !== "")
    return [{
      id,
      title: text(record.title, id),
      description: text(record.description, text(record.title, id)),
      criterion_id: criterion(record.criterion).id as string,
      kind: record.kind === "violation" ? "violation" : "design_observation",
      components: components.length ? components : ["(unreported component)"],
      evidence_ids: list(record.evidence_ids).filter((item): item is string => typeof item === "string"),
      justification: text(record.justification, text(record.description, id)),
      modularity_impact: text(record.impact),
      severity: SEVERITIES.has(text(record.severity)) ? text(record.severity) : "info",
      confidence: confidence(record.technical_details),
      recommendation: text(record.recommendation),
      criterion: criterion(record.criterion),
      evidence: [],
      validation_status: validationStatus(record.verification_status),
      review_rationale: text(record.verification_rationale, "Persisted audit verification."),
    }]
  })
}

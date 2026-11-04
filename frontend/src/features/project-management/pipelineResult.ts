/** Claim certainty reported by the repository agents. Anything else is dropped. */
const CLAIM_STATUSES = new Set(["supported", "hypothesis", "unresolved"])

/** Review verdicts of the semantic validation stage. */
const REVIEW_VERDICTS = new Set(["accepted", "revisions_needed", "needs_evidence", "inconclusive"])

/** Finding verdicts of a single reviewed claim. */
const FINDING_VERDICTS = new Set(["supported", "overstated", "contradicted", "insufficient_evidence"])

const COMPLETION_STATUSES = new Set(["complete", "partial", "failed"])

export interface OrientationComponentView {
  name: string
  responsibility: string
  status: string
}

export interface StartingPointView {
  fileId: string
  reason: string
}

export interface OrientationSummary {
  completionStatus: string
  projectType: string
  projectTypeStatus: string
  purpose: string
  purposeStatus: string
  components: OrientationComponentView[]
  startingPoints: StartingPointView[]
  uncertainties: string[]
}

export interface ArchitectureUnitView {
  name: string
  responsibility: string
  status: string
}

export interface ArchitectureConnectionView {
  from: string
  to: string
  description: string
}

export interface ArchitectureDeviationView {
  decision: string
  expectation: string
  explanation: string
}

export interface InfrastructureView {
  name: string
  kind: string
}

export interface ArchitectureDiagramView {
  title: string
  scope: string
  mermaid: string
  colorLegend: boolean
  limitations: string[]
  deviations: { id: string; observation: string; expectation: string; explanation: string }[]
}

export interface ProjectArchitectureSummary {
  completionStatus: string
  units: ArchitectureUnitView[]
  connections: ArchitectureConnectionView[]
  pattern: string
  patternAssessment: string
  explanation: string
  supportingFindings: { statement: string; status: string; scope: string; limitations: string[] }[]
  contrastQuestion: string
  contrastResult: string
  deviations: ArchitectureDeviationView[]
  infrastructure: InfrastructureView[]
  uncertainties: string[]
  diagramTitle: string
  diagramNodes: number
  diagramEdges: number
  /** Rendered Mermaid chart merged by the backend from the pipeline-level
   *  diagram; empty when the run predates diagrams, skipped composition, or
   *  the composition failed. */
  diagramMermaid: string
  diagramOrigin: string
  diagramViews: ArchitectureDiagramView[]
  relationshipCoverage: { unit: string; status: string; reason: string; pendingPaths: string[]; blocker: string; blockerReason: string }[]
}

export interface SemanticFindingView {
  targetId: string
  statement: string
  verdict: string
  reason: string
  correction: string
}

export interface SemanticValidationSummary {
  completionStatus: string
  verdict: string
  findings: SemanticFindingView[]
  pending: string[]
}

export interface StageIssueView {
  category: string
  message: string
}

export interface StageStatusSummary {
  completionStatus: string
  issues: StageIssueView[]
  limitations: string[]
}

function parseJsonObject(result: string | null): Record<string, unknown> | null {
  if (result === null || result.trim() === "") {
    return null
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(result) as unknown
  } catch {
    return null
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null
  }
  return parsed as Record<string, unknown>
}

function readString(record: Record<string, unknown>, key: string): string {
  return typeof record[key] === "string" ? (record[key] as string) : ""
}

function readStrings(value: unknown): string[] {
  if (Array.isArray(value) === false) {
    return []
  }
  return (value as unknown[]).filter((item): item is string => typeof item === "string")
}

function readCompletion(record: Record<string, unknown>): string | null {
  const status = readString(record, "completion_status")
  return COMPLETION_STATUSES.has(status) ? status : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function readClaim(entry: unknown): { statement: string; status: string } | null {
  if (!isRecord(entry)) {
    return null
  }
  const statement = readString(entry, "statement").trim()
  const status = readString(entry, "status").trim()
  if (statement === "" || !CLAIM_STATUSES.has(status)) {
    return null
  }
  return { statement, status }
}

/** The orientation result parsed out of its raw JSON result, if usable. */
export function parseOrientationResult(result: string | null): OrientationSummary | null {
  const record = parseJsonObject(result)
  const completionStatus = record === null ? null : readCompletion(record)
  if (record === null || completionStatus === null) {
    return null
  }
  const orientation = record["orientation"]
  if (!isRecord(orientation)) {
    return null
  }
  const projectType = isRecord(orientation["project_type"]) ? readClaim(orientation["project_type"]) : null
  const purpose = isRecord(orientation["purpose"]) ? readClaim(orientation["purpose"]) : null
  const components: OrientationComponentView[] = []
  if (Array.isArray(orientation["components"])) {
    for (const item of orientation["components"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const name = readString(item, "name").trim()
      const responsibility = readClaim(item["responsibility"])
      if (name === "" || responsibility === null) {
        continue
      }
      components.push({ name, responsibility: responsibility.statement, status: responsibility.status })
    }
  }
  const startingPoints: StartingPointView[] = []
  if (Array.isArray(orientation["starting_points"])) {
    for (const item of orientation["starting_points"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const fileId = readString(item, "file_id").trim()
      const reason = readString(item, "reason").trim()
      if (fileId === "" || reason === "") {
        continue
      }
      startingPoints.push({ fileId, reason })
    }
  }
  return {
    completionStatus,
    projectType: projectType?.statement ?? "",
    projectTypeStatus: projectType?.status ?? "",
    purpose: purpose?.statement ?? "",
    purposeStatus: purpose?.status ?? "",
    components,
    startingPoints,
    uncertainties: readStrings(orientation["uncertainties"]).map((item) => item.trim()).filter((item) => item !== ""),
  }
}

/** The project architecture report parsed out of its raw JSON result, if usable. */
export function parseProjectArchitectureResult(result: string | null): ProjectArchitectureSummary | null {
  const record = parseJsonObject(result)
  const completionStatus = record === null ? null : readCompletion(record)
  if (record === null || completionStatus === null) {
    return null
  }
  const report = record["architecture"]
  if (!isRecord(report)) {
    return null
  }
  const units: ArchitectureUnitView[] = []
  if (Array.isArray(report["organization"])) {
    for (const item of report["organization"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const name = readString(item, "name").trim()
      const responsibility = readClaim(item["responsibility"])
      if (name === "" || responsibility === null) {
        continue
      }
      units.push({ name, responsibility: responsibility.statement, status: responsibility.status })
    }
  }
  const connections: ArchitectureConnectionView[] = []
  if (Array.isArray(report["connections"])) {
    for (const item of report["connections"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const from = readString(item, "source_unit").trim()
      const to = readString(item, "target_unit").trim()
      const description = readClaim(item["description"])
      if (from === "" || to === "" || description === null) {
        continue
      }
      connections.push({ from, to, description: description.statement })
    }
  }
  const classification = isRecord(report["closest_architecture"]) ? (report["closest_architecture"] as Record<string, unknown>) : null
  const assessment = classification !== null && isRecord(classification["assessment"]) ? readClaim(classification["assessment"]) : null
  const deviations: ArchitectureDeviationView[] = []
  if (Array.isArray(report["deviations"])) {
    for (const item of report["deviations"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const decision = readClaim(item["observed_decision"])
      const expectation = readString(item, "pattern_expectation").trim()
      const explanation = readString(item, "explanation").trim()
      if (decision === null || expectation === "" || explanation === "") {
        continue
      }
      deviations.push({ decision: decision.statement, expectation, explanation })
    }
  }
  const infrastructure: InfrastructureView[] = []
  if (Array.isArray(report["infrastructure"])) {
    for (const item of report["infrastructure"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const name = readString(item, "name").trim()
      const kind = readString(item, "kind").trim()
      if (name === "" || kind === "") {
        continue
      }
      infrastructure.push({ name, kind })
    }
  }
  const diagram = isRecord(report["diagram"]) ? (report["diagram"] as Record<string, unknown>) : null
  const rendered = isRecord(record["architecture_diagram"]) ? (record["architecture_diagram"] as Record<string, unknown>) : null
  const mermaid = rendered === null || typeof rendered["mermaid"] !== "string" ? "" : (rendered["mermaid"] as string).trim()
  const origin = rendered === null || typeof rendered["report_origin"] !== "string" || (rendered["report_origin"] as string).trim() === ""
    ? ""
    : (rendered["report_origin"] as string).trim()
  const diagramViews: ArchitectureDiagramView[] = []
  for (const artifact of rendered === null ? [] : [rendered, ...(Array.isArray(rendered["views"]) ? rendered["views"] : [])]) {
    if (!isRecord(artifact)) continue
    const chart = readString(artifact, "mermaid").trim()
    if (chart === "") continue
    const structure = isRecord(artifact["structure"]) ? artifact["structure"] : {}
    diagramViews.push({
      title: readString(structure, "title").trim() || (diagram === null ? "" : readString(diagram, "title").trim()),
      scope: readString(structure, "scope").trim(),
      mermaid: chart,
      colorLegend: Array.isArray(artifact["legend"]) && artifact["legend"].length > 0,
      limitations: readStrings(artifact["limitations"]),
      deviations: (Array.isArray(artifact["deviation_notes"]) ? artifact["deviation_notes"] : []).flatMap((note: unknown) => isRecord(note) ? [{
        id: readString(note, "id"), observation: readString(note, "observation"), expectation: readString(note, "expectation"), explanation: readString(note, "explanation"),
      }] : []),
    })
  }
  return {
    completionStatus,
    units,
    connections,
    pattern: classification === null ? "" : readString(classification, "pattern").trim(),
    patternAssessment: assessment?.statement ?? "",
    explanation: readClaim(report["explanation"])?.statement ?? "",
    supportingFindings: (Array.isArray(report["supporting_evidence"]) ? report["supporting_evidence"] : []).flatMap((item: unknown) => {
      const claim = readClaim(item)
      return claim && isRecord(item) ? [{ ...claim, scope: readString(item, "scope").trim(), limitations: readStrings(item["limitations"]) }] : []
    }),
    contrastQuestion: classification === null ? "" : readString(classification, "contrast_question").trim(),
    contrastResult: classification === null ? "" : readClaim(classification["contrast_result"])?.statement ?? "",
    deviations,
    infrastructure,
    uncertainties: readStrings(report["uncertainties"]).map((item) => item.trim()).filter((item) => item !== ""),
    diagramTitle: diagram === null ? "" : readString(diagram, "title").trim(),
    diagramNodes: diagram === null || !Array.isArray(diagram["nodes"]) ? 0 : (diagram["nodes"] as unknown[]).length,
    diagramEdges: diagram === null || !Array.isArray(diagram["edges"]) ? 0 : (diagram["edges"] as unknown[]).length,
    diagramMermaid: mermaid,
    diagramOrigin: origin,
    diagramViews,
    relationshipCoverage: (Array.isArray(record["relationship_coverage"]) ? record["relationship_coverage"] : []).flatMap((item: unknown) => isRecord(item) && readString(item, "unit_name").trim() !== "" ? [{
      unit: readString(item, "unit_name"), status: readString(item, "status"), reason: readString(item, "reason"), pendingPaths: readStrings(item["pending_paths"]), blocker: readString(item, "resolution_blocker"), blockerReason: readString(item, "blocker_reason"),
    }] : []),
  }
}

/** The semantic validation review parsed out of its raw JSON result, if usable. */
export function parseSemanticValidationResult(result: string | null): SemanticValidationSummary | null {
  const record = parseJsonObject(result)
  const completionStatus = record === null ? null : readCompletion(record)
  if (record === null || completionStatus === null) {
    return null
  }
  const verdict = readString(record, "verdict").trim()
  if (!REVIEW_VERDICTS.has(verdict)) {
    return null
  }
  const findings: SemanticFindingView[] = []
  if (Array.isArray(record["findings"])) {
    for (const item of record["findings"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const targetId = readString(item, "target_id").trim()
      const statement = readString(item, "checked_statement").trim()
      const findingVerdict = readString(item, "verdict").trim()
      if (targetId === "" || statement === "" || !FINDING_VERDICTS.has(findingVerdict)) {
        continue
      }
      const correction = isRecord(item["correction"]) ? readString(item["correction"] as Record<string, unknown>, "statement").trim() : ""
      findings.push({
        targetId,
        statement,
        verdict: findingVerdict,
        reason: readString(item, "reason").trim(),
        correction,
      })
    }
  }
  return {
    completionStatus,
    verdict,
    findings,
    pending: readStrings(record["pending_target_ids"]).map((item) => item.trim()).filter((item) => item !== ""),
  }
}

/** Fallback for any stage result, including runs whose report is null: the
 *  completion status plus what went wrong, so failed runs still explain
 *  themselves instead of falling back to a bare run status. */
export function parseStageStatus(result: string | null): StageStatusSummary | null {
  const record = parseJsonObject(result)
  const completionStatus = record === null ? null : readCompletion(record)
  if (record === null || completionStatus === null) {
    return null
  }
  const issues: StageIssueView[] = []
  if (Array.isArray(record["execution_issues"])) {
    for (const item of record["execution_issues"] as unknown[]) {
      if (!isRecord(item)) {
        continue
      }
      const category = readString(item, "category").trim()
      const message = readString(item, "message").trim()
      if (category === "" || message === "") {
        continue
      }
      issues.push({ category, message })
    }
  }
  return {
    completionStatus,
    issues,
    limitations: readStrings(record["limitations"]).map((item) => item.trim()).filter((item) => item !== ""),
  }
}

export function auditTone(status: string): "success" | "warning" | "info" {
  if (status === "Completed") {
    return "success"
  }
  if (status === "Failed") {
    return "warning"
  }
  return "info"
}

/** Tone for claim certainty and review verdicts. */
export function verdictTone(verdict: string): "success" | "warning" | "info" {
  if (verdict === "supported" || verdict === "accepted") {
    return "success"
  }
  if (verdict === "contradicted") {
    return "warning"
  }
  return "info"
}

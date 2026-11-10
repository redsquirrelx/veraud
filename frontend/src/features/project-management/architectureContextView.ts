import type { ParseKeys } from "i18next"

export const ARCHITECTURE_CONTEXT_CATEGORIES = [
  "architectural_style",
  "components",
  "responsibilities",
  "relationships",
  "constraints",
  "interfaces_and_contracts",
  "architectural_decisions",
] as const

export type ArchitectureContextCategory = (typeof ARCHITECTURE_CONTEXT_CATEGORIES)[number]

const CATEGORY_SET = new Set<string>(ARCHITECTURE_CONTEXT_CATEGORIES)

export const architectureContextCategoryLabelKeys: Record<string, ParseKeys<"projects">> = {
  architectural_style: "detail.overview.architectureContext.categories.architecturalStyle",
  components: "detail.overview.architectureContext.categories.components",
  responsibilities: "detail.overview.architectureContext.categories.responsibilities",
  relationships: "detail.overview.architectureContext.categories.relationships",
  constraints: "detail.overview.architectureContext.categories.constraints",
  interfaces_and_contracts: "detail.overview.architectureContext.categories.interfacesAndContracts",
  architectural_decisions: "detail.overview.architectureContext.categories.architecturalDecisions",
}

export const architectureContextCategoryDescriptionLabelKeys: Record<string, ParseKeys<"projects">> = {
  architectural_style: "detail.overview.architectureContext.categoryDescriptions.architecturalStyle",
  components: "detail.overview.architectureContext.categoryDescriptions.components",
  responsibilities: "detail.overview.architectureContext.categoryDescriptions.responsibilities",
  relationships: "detail.overview.architectureContext.categoryDescriptions.relationships",
  constraints: "detail.overview.architectureContext.categoryDescriptions.constraints",
  interfaces_and_contracts: "detail.overview.architectureContext.categoryDescriptions.interfacesAndContracts",
  architectural_decisions: "detail.overview.architectureContext.categoryDescriptions.architecturalDecisions",
}

export const architectureContextCertaintyLabelKeys: Record<string, ParseKeys<"projects">> = {
  explicit: "detail.overview.architectureContext.certainty.explicit",
  derived: "detail.overview.architectureContext.certainty.derived",
  unknown: "detail.overview.architectureContext.certainty.unknown",
}

export const architectureContextConstraintLabelKeys: Record<string, ParseKeys<"projects">> = {
  allowed: "detail.overview.architectureContext.constraint.allowed",
  prohibited: "detail.overview.architectureContext.constraint.prohibited",
  required: "detail.overview.architectureContext.constraint.required",
  exception: "detail.overview.architectureContext.constraint.exception",
}

export const architectureContextIssueKindLabelKeys: Record<string, ParseKeys<"projects">> = {
  unknown: "detail.overview.architectureContext.issueKind.unknown",
  ambiguity: "detail.overview.architectureContext.issueKind.ambiguity",
  discrepancy: "detail.overview.architectureContext.issueKind.discrepancy",
}

export const architectureContextCoverageLabelKeys: Record<string, ParseKeys<"projects">> = {
  completed: "detail.overview.architectureContext.coverageStatus.completed",
  failed: "detail.overview.architectureContext.coverageStatus.failed",
  not_run: "detail.overview.architectureContext.coverageStatus.notRun",
}

export const architectureContextReasonLabelKeys: Record<string, ParseKeys<"projects">> = {
  coverage_complete: "detail.overview.architectureContext.reasonValues.coverageComplete",
  incomplete_coverage: "detail.overview.architectureContext.reasonValues.incompleteCoverage",
  pending_categories: "detail.overview.architectureContext.reasonValues.pendingCategories",
  retrieval_incomplete: "detail.overview.architectureContext.reasonValues.retrievalIncomplete",
  coverage_not_evaluated: "detail.overview.architectureContext.reasonValues.coverageNotEvaluated",
  document_discovery_failed: "detail.overview.architectureContext.reasonValues.documentDiscoveryFailed",
  validation_failed: "detail.overview.architectureContext.reasonValues.validationFailed",
  extraction_failed: "detail.overview.architectureContext.reasonValues.extractionFailed",
  extraction_context_exhausted: "detail.overview.architectureContext.reasonValues.extractionContextExhausted",
  coverage_assessment_failed: "detail.overview.architectureContext.reasonValues.coverageAssessmentFailed",
  coverage_context_exhausted: "detail.overview.architectureContext.reasonValues.coverageContextExhausted",
}

export interface ArchitectureContextEvidenceView {
  label: string
  filePath: string
  startLine: number | null
  endLine: number | null
  lines: string
  quote: string
}

export interface ArchitectureContextClaimView {
  category: string
  subject: string
  statement: string
  relatedSubjects: string[]
  certainty: string
  constraint: string
  reasoning: string
  sectionIds: string[]
  evidence: ArchitectureContextEvidenceView[]
}

export interface ArchitectureContextIssueView {
  category: string
  kind: string
  question: string
  sectionIds: string[]
  documentReferences: string[]
}

export interface ArchitectureContextDiagnosticView {
  target: string
  position: number | null
  sectionIds: string[]
  reason: string
}

export interface ArchitectureContextDocumentView {
  path: string
  lineCount: number | null
  contentHash: string
}

export interface ArchitectureContextSummary {
  knowledge: ArchitectureContextClaimView[]
  issues: ArchitectureContextIssueView[]
  coveredCategories: string[]
  pendingCategories: string[]
  evaluatedCategories: string[]
  coverageAssessmentStatus: string
  consultedDocuments: ArchitectureContextDocumentView[]
  validationErrors: ArchitectureContextDiagnosticView[]
  finalizationReason: string
  executionError: string
}

export type ArchitectureContextCoverageState = "complete" | "partial" | "missing"

export interface ArchitectureContextCoverageStats {
  total: number
  covered: number
  partial: number
  missing: number
  percent: number
  coveredPercent: number
  partialPercent: number
  state: ArchitectureContextCoverageState
}

export type ArchitectureContextCategoryCoverageState = "covered" | "partial" | "missing"

export interface ArchitectureContextCategorySource {
  label: string
  filePath: string
  startLine: number | null
  endLine: number | null
  lines: string
  quote: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === "string" ? value.trim() : ""
}

function readNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key]
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function readStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter((item) => item !== "")
}

function readCategories(value: unknown): string[] {
  const categories = readStrings(value).filter((item) => CATEGORY_SET.has(item))
  return ARCHITECTURE_CONTEXT_CATEGORIES.filter((category) => categories.includes(category))
}

function readSectionPaths(value: unknown): Map<string, string> {
  const paths = new Map<string, string>()
  if (!isRecord(value)) return paths
  for (const [sectionId, path] of Object.entries(value)) {
    if (typeof path === "string" && path.trim() !== "") paths.set(sectionId, path.trim())
  }
  return paths
}

function sectionLabel(sectionId: string, sectionPaths: Map<string, string>): string {
  return sectionPaths.get(sectionId) ?? sectionId
}

function readEvidence(value: unknown, sectionPaths: Map<string, string>): ArchitectureContextEvidenceView[] {
  if (!Array.isArray(value)) return []
  const evidence: ArchitectureContextEvidenceView[] = []
  for (const item of value) {
    if (!isRecord(item)) continue
    const sectionId = readString(item, "section_id")
    if (sectionId === "") continue
    const start = readNumber(item, "start_line")
    const end = readNumber(item, "end_line")
    const filePath = sectionLabel(sectionId, sectionPaths)
    evidence.push({
      label: filePath,
      filePath,
      startLine: start !== null && Number.isInteger(start) && start > 0 ? start : null,
      endLine: end !== null && Number.isInteger(end) && end > 0 ? end : null,
      lines: start !== null && end !== null ? `${start}–${end}` : "",
      quote: readString(item, "quote"),
    })
  }
  return evidence
}

function readClaim(value: unknown, sectionPaths: Map<string, string>): ArchitectureContextClaimView | null {
  if (!isRecord(value)) return null
  const category = readString(value, "category")
  const subject = readString(value, "subject")
  const statement = readString(value, "statement")
  if (!CATEGORY_SET.has(category) || subject === "" || statement === "") return null
  const sectionIds = readStrings(value["section_ids"])
  const evidence = readEvidence(value["evidence"], sectionPaths)
  return {
    category,
    subject,
    statement,
    relatedSubjects: readStrings(value["related_subjects"]),
    certainty: readString(value, "certainty"),
    constraint: readString(value, "constraint"),
    reasoning: readString(value, "reasoning"),
    sectionIds,
    evidence: evidence.length > 0 ? evidence : sectionIds.map((sectionId) => ({
      label: sectionLabel(sectionId, sectionPaths),
      filePath: sectionLabel(sectionId, sectionPaths),
      startLine: null,
      endLine: null,
      lines: "",
      quote: "",
    })),
  }
}

function readIssue(value: unknown, sectionPaths: Map<string, string>): ArchitectureContextIssueView | null {
  if (!isRecord(value)) return null
  const category = readString(value, "category")
  const question = readString(value, "question")
  if (!CATEGORY_SET.has(category) || question === "") return null
  return {
    category,
    kind: readString(value, "kind"),
    question,
    sectionIds: readStrings(value["section_ids"]).map((sectionId) => sectionLabel(sectionId, sectionPaths)),
    documentReferences: readStrings(value["document_references"]),
  }
}

function readDiagnostic(value: unknown, sectionPaths: Map<string, string>): ArchitectureContextDiagnosticView | null {
  if (!isRecord(value)) return null
  const reason = readString(value, "reason")
  if (reason === "") return null
  return {
    target: readString(value, "target"),
    position: readNumber(value, "position"),
    sectionIds: readStrings(value["section_ids"]).map((sectionId) => sectionLabel(sectionId, sectionPaths)),
    reason,
  }
}

function readDocument(value: unknown): ArchitectureContextDocumentView | null {
  if (!isRecord(value)) return null
  const path = readString(value, "path")
  if (path === "") return null
  return { path, lineCount: readNumber(value, "line_count"), contentHash: readString(value, "content_hash") }
}

function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** Typed projection of an `ArchitectureContextResult` payload, for display. */
export function parseArchitectureContext(data: Record<string, unknown>): ArchitectureContextSummary {
  const sectionPaths = readSectionPaths(data["section_paths"])
  return {
    knowledge: readArray(data["knowledge"]).flatMap((item) => {
      const claim = readClaim(item, sectionPaths)
      return claim === null ? [] : [claim]
    }),
    issues: readArray(data["knowledge_issues"]).flatMap((item) => {
      const issue = readIssue(item, sectionPaths)
      return issue === null ? [] : [issue]
    }),
    coveredCategories: readCategories(data["covered_categories"]),
    pendingCategories: readCategories(data["pending_categories"]),
    evaluatedCategories: readCategories(data["evaluated_categories"]),
    coverageAssessmentStatus: readString(data, "coverage_assessment_status"),
    consultedDocuments: readArray(data["consulted_documents"]).flatMap((item) => {
      const document = readDocument(item)
      return document === null ? [] : [document]
    }),
    validationErrors: readArray(data["validation_errors"]).flatMap((item) => {
      const diagnostic = readDiagnostic(item, sectionPaths)
      return diagnostic === null ? [] : [diagnostic]
    }),
    finalizationReason: readString(data, "finalization_reason"),
    executionError: readString(data, "execution_error"),
  }
}

export function getCoverageStats(summary: ArchitectureContextSummary): ArchitectureContextCoverageStats {
  const total: number = ARCHITECTURE_CONTEXT_CATEGORIES.length
  const covered = summary.coveredCategories.length
  const coveredCategories = new Set(summary.coveredCategories)
  const partial = ARCHITECTURE_CONTEXT_CATEGORIES.filter((category) =>
    !coveredCategories.has(category)
    && (summary.knowledge.some((claim) => claim.category === category) || summary.evaluatedCategories.includes(category)),
  ).length
  const missing = Math.max(0, total - covered - partial)
  const coveredPercent = total === 0 ? 0 : Math.round((covered / total) * 100)
  const partialPercent = total === 0 ? 0 : Math.round((partial / total) * 100)
  const percent = coveredPercent + partialPercent
  const state: ArchitectureContextCoverageState = covered === total ? "complete" : covered + partial > 0 ? "partial" : "missing"
  return { total, covered, partial, missing, percent, coveredPercent, partialPercent, state }
}

export function getCategoryCoverageState(summary: ArchitectureContextSummary, category: string): ArchitectureContextCategoryCoverageState {
  if (summary.coveredCategories.includes(category)) return "covered"
  const hasKnowledge = summary.knowledge.some((claim) => claim.category === category)
  const evaluated = summary.evaluatedCategories.includes(category)
  return hasKnowledge || evaluated ? "partial" : "missing"
}

export function parseEvidenceReference(reference: string): { filePath: string; startLine: number | null; endLine: number | null } {
  const normalized = reference.trim()
  const match = /^(.+):([1-9][0-9]*)(?:-([1-9][0-9]*))?$/.exec(normalized)
  if (match === null || /^[a-z][a-z0-9+.-]*:/i.test(normalized)) {
    return { filePath: normalized, startLine: null, endLine: null }
  }
  const startLine = Number(match[2])
  const endLine = match[3] === undefined ? startLine : Number(match[3])
  return {
    filePath: match[1]!.trim(),
    startLine: Number.isInteger(startLine) && startLine > 0 ? startLine : null,
    endLine: Number.isInteger(endLine) && endLine > 0 ? endLine : null,
  }
}

export function getClaimSources(claim: ArchitectureContextClaimView): ArchitectureContextCategorySource[] {
  return claim.evidence.map((evidence) => {
    const filePath = evidence.filePath || evidence.label
    return {
      label: filePath,
      filePath,
      startLine: evidence.startLine,
      endLine: evidence.endLine,
      lines: evidence.lines,
      quote: evidence.quote,
    }
  })
}

export function groupCategorySources(sources: ArchitectureContextCategorySource[]): { filePath: string; references: ArchitectureContextCategorySource[] }[] {
  const groups = new Map<string, ArchitectureContextCategorySource[]>()
  for (const source of sources) {
    groups.set(source.filePath, [...(groups.get(source.filePath) ?? []), source])
  }
  return [...groups.entries()].map(([filePath, references]) => ({ filePath, references }))
}

export function getCategorySources(summary: ArchitectureContextSummary, category: string): ArchitectureContextCategorySource[] {
  const sources: ArchitectureContextCategorySource[] = []
  const seen = new Set<string>()
  const addSource = (source: ArchitectureContextCategorySource) => {
    const key = `${source.filePath}\n${source.startLine ?? ""}\n${source.endLine ?? ""}\n${source.quote}`
    if (seen.has(key) || source.filePath === "") return
    seen.add(key)
    sources.push(source)
  }
  for (const claim of summary.knowledge) {
    if (claim.category !== category) continue
    for (const evidence of claim.evidence) {
      const filePath = evidence.filePath || evidence.label
      addSource({
        label: filePath,
        filePath,
        startLine: evidence.startLine,
        endLine: evidence.endLine,
        lines: evidence.lines,
        quote: evidence.quote,
      })
    }
  }
  for (const issue of summary.issues) {
    if (issue.category !== category) continue
    for (const reference of [...issue.sectionIds, ...issue.documentReferences]) {
      const parsed = parseEvidenceReference(reference)
      addSource({
        label: parsed.filePath,
        filePath: parsed.filePath,
        startLine: parsed.startLine,
        endLine: parsed.endLine,
        lines: parsed.startLine !== null ? `L${parsed.startLine}–L${parsed.endLine ?? parsed.startLine}` : "",
        quote: "",
      })
    }
  }
  return sources
}

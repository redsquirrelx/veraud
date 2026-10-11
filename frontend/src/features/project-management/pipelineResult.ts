const ANALYSIS_KINDS = new Set([
  "cli",
  "library",
  "web_service",
  "desktop_app",
  "data_pipeline",
  "script",
  "unknown",
])

const CONFIDENCES = new Set(["low", "medium", "high"])

/** ISO/IEC 25010 maintainability sub-characteristics, the only ones the
 *  architect may report. Anything else is dropped, mirroring the backend. */
const CHARACTERISTICS = new Set([
  "modularity",
  "analysability",
  "modifiability",
  "testability",
])

export interface AnalyzerSummary {
  kind: string
  confidence: string
  summary: string
  primaryLanguage: string
  entrypoints: string[]
  keyComponents: string[]
  filesRead: number | null
  hypothesisConfirmed: boolean | null
}

export interface DeviationView {
  observation: string
  evidence: string[]
}

export interface ComponentView {
  path: string
  responsibility: string
}

export interface QualityNoteView {
  characteristic: string
  observation: string
  evidence: string[]
}

export interface ArchitectureSummary {
  style: string
  intendedStyle: string
  deviations: DeviationView[]
  components: ComponentView[]
  dataFlow: string
  thirdParty: string[]
  cycles: string[][]
  qualityNotes: QualityNoteView[]
  risks: string[]
  confidence: string
  diagramContainers: string
  diagramComponents: string
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

/** The analyzer's verdict parsed out of its raw JSON result, if usable. */
export function parseAnalyzerResult(result: string | null): AnalyzerSummary | null {
  const record = parseJsonObject(result)
  if (record === null) {
    return null
  }
  const kind = readString(record, "kind")
  const confidence = readString(record, "confidence")
  if (!ANALYSIS_KINDS.has(kind) || !CONFIDENCES.has(confidence)) {
    return null
  }
  const filesRead = typeof record["files_read"] === "number" ? (record["files_read"] as number) : null
  const hypothesisConfirmed = typeof record["hypothesis_confirmed"] === "boolean"
    ? (record["hypothesis_confirmed"] as boolean)
    : null
  return {
    kind,
    confidence,
    summary: readString(record, "summary").trim(),
    primaryLanguage: readString(record, "primary_language").trim(),
    entrypoints: readStrings(record["entrypoints"]),
    keyComponents: readStrings(record["key_components"]),
    filesRead,
    hypothesisConfirmed,
  }
}

function readEvidence(item: Record<string, unknown>): string[] {
  return readStrings(item["evidence"])
}

/** The architect's description parsed out of its raw JSON result, if usable. */
export function parseArchitectureResult(result: string | null): ArchitectureSummary | null {
  const record = parseJsonObject(result)
  if (record === null) {
    return null
  }
  const style = readString(record, "style").trim() || "unknown"
  const confidence = readString(record, "confidence")
  if (!CONFIDENCES.has(confidence)) {
    return null
  }
  const deviations: DeviationView[] = []
  if (Array.isArray(record["deviations"])) {
    for (const item of record["deviations"] as unknown[]) {
      if (typeof item !== "object" || item === null) {
        continue
      }
      const entry = item as Record<string, unknown>
      const observation = readString(entry, "observation").trim()
      if (observation === "") {
        continue
      }
      deviations.push({ observation, evidence: readEvidence(entry) })
    }
  }
  const components: ComponentView[] = []
  if (Array.isArray(record["components"])) {
    for (const item of record["components"] as unknown[]) {
      if (typeof item !== "object" || item === null) {
        continue
      }
      const entry = item as Record<string, unknown>
      const path = readString(entry, "path").trim()
      if (path === "") {
        continue
      }
      components.push({ path, responsibility: readString(entry, "responsibility").trim() })
    }
  }
  const cycles: string[][] = []
  if (Array.isArray(record["cycles"])) {
    for (const item of record["cycles"] as unknown[]) {
      const group = readStrings(item).map((path) => path.trim()).filter((path) => path !== "")
      if (group.length > 1) {
        cycles.push(group)
      }
    }
  }
  const qualityNotes: QualityNoteView[] = []
  if (Array.isArray(record["quality_notes"])) {
    for (const item of record["quality_notes"] as unknown[]) {
      if (typeof item !== "object" || item === null) {
        continue
      }
      const entry = item as Record<string, unknown>
      const characteristic = readString(entry, "characteristic").trim().toLowerCase()
      const observation = readString(entry, "observation").trim()
      if (!CHARACTERISTICS.has(characteristic) || observation === "") {
        continue
      }
      qualityNotes.push({ characteristic, observation, evidence: readEvidence(entry) })
    }
  }
  const risks = readStrings(record["risks"]).map((risk) => risk.trim()).filter((risk) => risk !== "")
  return {
    style,
    intendedStyle: readString(record, "intended_style").trim() || "unknown",
    deviations,
    components,
    dataFlow: readString(record, "data_flow").trim(),
    thirdParty: readStrings(record["third_party"]).map((name) => name.trim()).filter((name) => name !== ""),
    cycles,
    qualityNotes,
    risks,
    confidence,
    diagramContainers: readString(record, "diagram_containers").trim(),
    diagramComponents: readString(record, "diagram_components").trim(),
  }
}

export function kindTone(kind: string): "info" | "neutral" {
  return kind === "unknown" ? "neutral" : "info"
}

export function confidenceTone(confidence: string): "success" | "info" | "warning" {
  if (confidence === "high") {
    return "success"
  }
  if (confidence === "medium") {
    return "info"
  }
  return "warning"
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

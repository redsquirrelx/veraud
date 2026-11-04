const record = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as Record<string, unknown> : null
const text = (value: unknown): string | null => typeof value === "string" && value.length > 0 ? value : null
const line = (value: unknown): number | null => typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null

/** Match the Files page's relative checkout paths, without guessing absolute paths. */
export function evidenceFilePath(source: string | null, repositoryName = ""): string | null {
  if (!source) return null
  let path = source.trim().replaceAll("\\", "/")
  if (repositoryName && path.startsWith(`${repositoryName}/`)) path = path.slice(repositoryName.length + 1)
  if (!path || path.startsWith("/") || /^[a-z][a-z\d+.-]*:/i.test(path)
    || path.includes("\0") || path.split("/").some((segment) => !segment || [".", "..", ".git"].includes(segment))) return null
  return path
}

export interface AgentEvidence {
  id: string
  agentId: string
  invocationId: string | null
  kind: string | null
  source: string | null
  content: string | null
  startLine: number | null
  endLine: number | null
  commit: string | null
  toolCallId: string | null
  symbolIds: string[]
  symbols?: EvidenceSymbol[]
  commitVerification?: string | null
}

export interface EvidenceSymbol {
  id: string
  name: string | null
  kind: string | null
  source: string | null
  startLine: number | null
  endLine: number | null
  label: string | null
}

/** The report formatter emits `name — path:start–end` (or just path:start–end).
 * Read that explicit location, never infer it from an opaque symbol identifier. */
function symbolLabel(id: string, label: string | null): EvidenceSymbol {
  const unresolved = { id, name: null, kind: null, source: null, startLine: null, endLine: null, label }
  if (!label) return unresolved
  const match = /^(?:(.+) — )?(.+):([1-9]\d*)–([1-9]\d*)$/.exec(label)
  if (!match) return unresolved
  const source = evidenceFilePath(match[2])
  const start = line(Number(match[3]))
  const end = line(Number(match[4]))
  if (!source || start === null || end === null || end < start) return unresolved
  return { id, name: match[1] ?? null, kind: null, source, startLine: start, endLine: end, label }
}

/** Symbol IDs are shared across this audit. Repository/other-agent metadata can
 * resolve an investigator's symbols without changing ownership of its evidence. */
function recordedSymbols(annexes: Record<string, unknown>, ids: string[]): EvidenceSymbol[] {
  const candidates = new Map<string, EvidenceSymbol[]>()
  const requested = new Set(ids)
  const objects: Record<string, unknown>[] = []
  const files = new Map<string, Set<string>>()
  const addFile = (id: string | null, path: string | null) => {
    if (id && path) files.set(id, new Set([...(files.get(id) ?? []), path]))
  }
  const visit = (value: unknown) => {
    if (Array.isArray(value)) { value.forEach(visit); return }
    const item = record(value)
    if (!item) return
    objects.push(item)
    addFile(text(item.file_id) ?? (item.kind === "file" ? text(item.id) : null), text(item.path) ?? text(item.file_path) ?? text(item.source))
    for (const [key, child] of Object.entries(item)) if (key !== "content") visit(child)
  }
  for (const item of Array.isArray(annexes.evidence_inventory) ? annexes.evidence_inventory : []) {
    const evidence = record(item)
    addFile(text(evidence?.file_id), text(evidence?.source))
  }
  for (const execution of (Array.isArray(annexes.executions) ? annexes.executions : []).map(record)) visit(execution?.recorded_results)
  visit(annexes.metrics_and_tool_results)
  for (const item of objects) {
    const id = text(item.symbol_id) ?? text(item.declaration_id) ?? text(item.id)
      ?? (text(item.symbol_name) && Array.isArray(item.symbol_ids) && item.symbol_ids.length === 1 ? text(item.symbol_ids[0]) : null)
    if (!id || !requested.has(id)) continue
    const paths = files.get(text(item.file_id) ?? "")
    const symbol = { id, name: text(item.qualified_name) ?? text(item.symbol_name) ?? text(item.name),
      kind: item.kind === "symbol" ? null : text(item.kind),
      source: text(item.path) ?? text(item.file_path) ?? text(item.source) ?? (paths?.size === 1 ? [...paths][0] ?? null : null),
      startLine: line(item.start_line), endLine: line(item.end_line), label: null }
    candidates.set(id, [...(candidates.get(id) ?? []), symbol])
  }
  return ids.map((id) => {
    const values = candidates.get(id) ?? []
    const label = text(record(annexes.reference_labels)?.[id])
    const result: EvidenceSymbol = { id, name: null, kind: null, source: null, startLine: null, endLine: null, label }
    // Merge complementary metadata, but do not use labels to override conflicts.
    for (const key of ["name", "kind", "source", "startLine", "endLine"] as const) {
      if (new Set(values.map((value) => value[key]).filter((value) => value !== null)).size > 1) return result
    }
    const parsedLabel = symbolLabel(id, label)
    const fallback = values.every((value) => (["name", "source", "startLine", "endLine"] as const)
      .every((key) => value[key] === null || parsedLabel[key] === null || value[key] === parsedLabel[key])) ? parsedLabel : result
    return { ...result, name: values.find((value) => value.name)?.name ?? fallback.name,
      kind: values.find((value) => value.kind)?.kind ?? null,
      source: values.find((value) => value.source)?.source ?? fallback.source,
      startLine: values.find((value) => value.startLine)?.startLine ?? fallback.startLine,
      endLine: values.find((value) => value.endLine)?.endLine ?? fallback.endLine }
  })
}

/** Findings own the many-to-many relationship; evidence does not own a finding ID. */
export function findingsForEvidence(data: unknown, evidenceId: string): Record<string, unknown>[] {
  const findings = record(data)?.findings
  return Array.isArray(findings) ? findings.map(record).filter((finding): finding is Record<string, unknown> =>
    finding !== null && text(finding.id) !== null && Array.isArray(finding.evidence_ids) && finding.evidence_ids.includes(evidenceId)) : []
}

/** Resolve a link through this audit's inventory, never a finding's detecting
 * agent: findings may cite evidence produced by another investigator. */
export function auditEvidenceOwner(data: unknown, evidenceId: string): string | null {
  const inventory = record(data)?.evidence_inventory
  if (!Array.isArray(inventory)) return null
  const matches = inventory.map(record).filter((item) => item?.id === evidenceId)
  if (matches.length !== 1) return null
  return text(record(matches[0]?.provenance)?.agent_id)
}

/** Resolve the investigator from recorded identity, then retain all its evidence
 * in this audit, regardless of which invocation originally published it. */
export function readAgentEvidence(data: unknown, invocationId: string, recordedAgentId?: string) {
  const annexes = record(data)
  if (!annexes) return null
  const executions = Array.isArray(annexes.executions) ? annexes.executions : []
  const trace = executions.map(record).find((item) => item?.invocation_id === invocationId)
  const inventoryAvailable = Array.isArray(annexes.evidence_inventory)
  const inventory: unknown[] = inventoryAvailable ? annexes.evidence_inventory as unknown[] : []
  const original = inventory.map(record).find((item) => {
    const provenance = record(item?.provenance)
    return provenance?.invocation_id === invocationId && text(provenance.agent_id) !== null
  })
  const agentId = text(trace?.agent_id) ?? text(record(original?.provenance)?.agent_id) ?? text(recordedAgentId)
  const evidence: AgentEvidence[] = []
  for (const value of inventory) {
    const item = record(value)
    const provenance = record(item?.provenance)
    const id = text(item?.id)
    const owner = text(provenance?.agent_id)
    if (!item || !id || !agentId || owner !== agentId) continue
    evidence.push({ id, agentId: owner, invocationId: text(provenance?.invocation_id), kind: text(item.kind), source: text(item.source),
      content: typeof item.content === "string" ? item.content : null, startLine: line(item.start_line), endLine: line(item.end_line),
      commit: text(item.commit), commitVerification: text(item.commit_verification), toolCallId: text(item.tool_call_id),
      symbolIds: Array.isArray(item.symbol_ids) ? item.symbol_ids.filter((id): id is string => typeof id === "string" && id.length > 0) : [] })
  }
  const symbols = agentId ? new Map(recordedSymbols(annexes, [...new Set(evidence.flatMap((item) => item.symbolIds))])
    .map((symbol) => [symbol.id, symbol])) : new Map<string, EvidenceSymbol>()
  for (const item of evidence) item.symbols = item.symbolIds.flatMap((id) => symbols.get(id) ? [symbols.get(id)!] : [])
  return { agentId, evidence, inventoryAvailable, found: agentId !== null }
}

export function evidenceDisplayKind(evidence: AgentEvidence): "file" | "symbol" | "snippet" | null {
  if (evidence.kind === "symbol" || evidence.symbolIds.length > 0) return "symbol"
  if (evidence.kind === "file") return "file"
  if (["source", "code", "snippet", "code_fragment"].includes(evidence.kind ?? "")) return evidence.startLine !== null ? "snippet" : "file"
  return null
}

/** The existing content can be an excerpt. Only mark source coordinates when
 * its origin is known; never fetch today's file to fill an historical gap. */
export function evidenceCodeLocation(evidence: AgentEvidence) {
  const count = evidence.content === null || evidence.content === "" ? 0 : evidence.content.replace(/\n$/, "").split("\n").length
  const { startLine: start, endLine: end } = evidence
  if (start === null || end === null || end < start) return { firstLine: 1, range: null, unmapped: start !== null || end !== null }
  if (evidence.kind === "file" || start === 1) {
    return { firstLine: 1, range: end <= count ? { from: start, to: end } : null, unmapped: end > count }
  }
  if (count > 0 && count <= end - start + 1) {
    return { firstLine: start, range: { from: start, to: start + count - 1 }, unmapped: false }
  }
  return { firstLine: 1, range: null, unmapped: true }
}

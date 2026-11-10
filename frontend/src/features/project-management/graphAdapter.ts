/**
 * Architecture graph adapter for Graphify artifacts.
 *
 * Normalizes raw Graphify JSON, preserves all original IDs/relations, and
 * derives hierarchical views (system groups, module dependencies, symbols,
 * impact subgraphs) without mutating or discarding the original graph.
 *
 * Real artifacts (graphifyy v0.9.100) expose: directed, multigraph, graph,
 * nodes[], links[], hyperedges[], built_at_commit. Relations carry rich
 * metadata (relation, confidence/confidence_score, _origin, source_file,
 * source_location, weight, also_seen, context). This adapter is permissive:
 * it reads `links` or `edges` and ignores unknown fields rather than failing.
 */

import {
  classifyGraphNode,
  moduleIdFor,
  type GraphifyGraph,
  type GraphifyLink,
  type GraphifyNode,
  type GraphNodeKind,
} from "./structuralGraphModel.ts"

export type { GraphifyGraph, GraphifyLink, GraphifyNode, GraphNodeKind }
export { classifyGraphNode, moduleIdFor }

/** Every observed relation name. Unknown names are preserved as-is. */
export type RelationKind =
  | "imports"
  | "imports_from"
  | "references"
  | "contains"
  | "re_exports"
  | "calls"
  | "implements"
  | "inherits"
  | "declares"
  | "dynamic_import"
  | "method"
  | "rationale_for"
  | "indirect_call"
  | "uses"
  | (string & {})

export interface NormalizedNode {
  /** Original Graphify node ID (never modified). */
  id: string
  kind: GraphNodeKind
  label: string
  sourceFile: string | null
  sourceLocation: string | null
  fileType: string | null
  /** Original raw node (preserved for traceability/metadata). */
  raw: GraphifyNode
}

export interface NormalizedRelation {
  /** Stable derived id for UI keys; references original endpoints. */
  id: string
  source: string
  target: string
  relation: RelationKind | null
  confidence: string | null
  confidenceScore: number | null
  origin: string | null
  weight: number
  sourceFile: string | null
  sourceLocation: string | null
  /** Original raw link (preserved, never dropped). */
  raw: GraphifyLink
}

export interface CodeModule {
  /** Module/file node ID when a real module node exists, else synthetic `module:<sourceFile>`. */
  id: string
  label: string
  sourceFile: string | null
  sourceLocation: string | null
  directory: string
  /** Package-like grouping key (directory path). */
  groupKey: string
  /** IDs of class/function nodes belonging to this module. */
  symbolIds: string[]
  classCount: number
  functionCount: number
  inDegree: number
  outDegree: number
  synthetic: boolean
  raw: GraphifyNode | null
}

export type GroupingPerspective = "directory" | "community" | "external" | "coupling"
/** Backward-compatible alias. */
export type GroupingMode = GroupingPerspective

export interface ModuleGroup {
  id: string
  label: string
  kind: GroupingPerspective
  /** How the grouping was obtained: structural (JSON paths/markers), calculated (graph metrics), inferred. */
  evidence: "structural" | "calculated" | "inferred"
  parentId: string | null
  moduleIds: string[]
  moduleCount: number
  classCount: number
  functionCount: number
}

export interface AggregatedEdge {
  id: string
  source: string
  target: string
  /** Number of original relations represented. */
  weight: number
  /** Distinct original relation names represented. */
  relations: string[]
  /** Original relation IDs (traceability). */
  originalRelationIds: string[]
}

export interface SymbolNode {
  id: string
  label: string
  kind: "class" | "function"
  sourceFile: string | null
  sourceLocation: string | null
  moduleId: string
  /** For methods: owning class ID (from `method` relation), if known. */
  ownerClassId: string | null
  raw: GraphifyNode
}

export interface ImpactHit {
  nodeId: string
  depth: number
  direction: "out" | "in"
  /** Path of original relation IDs from the selected node to this node. */
  viaRelationIds: string[]
  observed: boolean
}

export interface ImpactGraph {
  centerId: string
  depth: number
  nodeIds: Set<string>
  hits: Map<string, ImpactHit>
  relationIds: Set<string>
}

export interface ArchitectureIndex {
  raw: GraphifyGraph
  nodesById: Map<string, NormalizedNode>
  relations: NormalizedRelation[]
  relationsById: Map<string, NormalizedRelation>
  outgoing: Map<string, NormalizedRelation[]>
  incoming: Map<string, NormalizedRelation[]>
  modulesById: Map<string, CodeModule>
  modules: CodeModule[]
  moduleIdByNodeId: Map<string, string>
  symbolsById: Map<string, SymbolNode>
  groupsByDirectory: ModuleGroup[]
  groupsByCommunity: ModuleGroup[]
  groupsByExternal: ModuleGroup[]
  groupsByCoupling: ModuleGroup[]
  moduleEdges: AggregatedEdge[]
  groupEdgesByDirectory: AggregatedEdge[]
  groupEdgesByCommunity: AggregatedEdge[]
  counts: { modules: number; classes: number; functions: number; relations: number; groups: number }
  builtAtCommit: string | null
}

const DEPENDENCY_RELATIONS = new Set<string>([
  "imports", "imports_from", "references", "calls", "uses", "inherits",
  "implements", "declares", "method", "indirect_call", "dynamic_import", "re_exports",
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/")
}

function directoryOf(sourceFile: string | null): string {
  if (sourceFile === null) return "(unknown)"
  const normalized = normalizePath(sourceFile)
  const index = normalized.lastIndexOf("/")
  return index <= 0 ? "(root)" : normalized.slice(0, index)
}

function labelFor(raw: GraphifyNode, sourceFile: string | null): string {
  const label = asString(raw.label)
  if (label !== null) return label
  if (sourceFile !== null) return normalizePath(sourceFile).split("/").pop() ?? sourceFile
  return raw.id
}

function rawLinksOf(graph: GraphifyGraph): unknown[] {
  if (Array.isArray(graph.links)) return graph.links
  if (Array.isArray(graph.edges)) return graph.edges
  return []
}

function isRawLink(value: unknown): value is GraphifyLink {
  return isRecord(value) && typeof value.source === "string" && typeof value.target === "string"
}

function isRawNode(value: unknown): value is GraphifyNode {
  return isRecord(value) && typeof value.id === "string"
}

export function buildArchitectureIndex(graph: GraphifyGraph): ArchitectureIndex {
  if (!isRecord(graph) || !Array.isArray(graph.nodes)) throw new Error("Invalid structural graph")
  const rawNodes = graph.nodes.filter(isRawNode)
  const rawLinks = rawLinksOf(graph).filter(isRawLink)

  const nodesById = new Map<string, NormalizedNode>()
  for (const raw of rawNodes) {
    const kind = classifyGraphNode(raw)
    const sourceFile = asString(raw.source_file)
    nodesById.set(raw.id, {
      id: raw.id, kind, label: labelFor(raw, sourceFile), sourceFile,
      sourceLocation: asString(raw.source_location), fileType: asString(raw.file_type), raw,
    })
  }

  const relations: NormalizedRelation[] = []
  const relationsById = new Map<string, NormalizedRelation>()
  const outgoing = new Map<string, NormalizedRelation[]>()
  const incoming = new Map<string, NormalizedRelation[]>()
  rawLinks.forEach((raw, index) => {
    if (!nodesById.has(raw.source) || !nodesById.has(raw.target)) return
    const rel: NormalizedRelation = {
      id: `rel:${index}:${raw.source}->${raw.target}`,
      source: raw.source, target: raw.target,
      relation: asString(raw.relation),
      confidence: asString(raw.confidence),
      confidenceScore: typeof raw.confidence_score === "number" ? raw.confidence_score : null,
      origin: asString(raw._origin),
      weight: typeof raw.weight === "number" && Number.isFinite(raw.weight) ? raw.weight : 1,
      sourceFile: asString(raw.source_file),
      sourceLocation: asString(raw.source_location),
      raw,
    }
    relations.push(rel)
    relationsById.set(rel.id, rel)
    ;(outgoing.get(rel.source) ?? outgoing.set(rel.source, []).get(rel.source)!).push(rel)
    ;(incoming.get(rel.target) ?? incoming.set(rel.target, []).get(rel.target)!).push(rel)
  })

  const { modulesById, modules, moduleIdByNodeId, symbolsById } = buildModules(nodesById)
  computeModuleDegrees(modulesById, moduleIdByNodeId, relations)

  const groupsByDirectory = buildDirectoryGroups(modules, 1)
  const groupsByCommunity = buildCommunityGroups(modules, nodesById)
  const groupsByExternal = buildExternalGroups(nodesById, relations, moduleIdByNodeId)
  const groupsByCoupling = buildCouplingGroups(modules)
  const moduleEdges = aggregateEdges(relations, (nodeId) => moduleIdByNodeId.get(nodeId) ?? null, (rel) => DEPENDENCY_RELATIONS.has(rel.relation ?? "") || rel.relation === "contains" || rel.relation === "rationale_for" ? rel.relation !== "contains" && rel.relation !== "rationale_for" : true)
  // For module dependency explorer, aggregate dependency-like relations (exclude pure structural contains/rationale to reduce noise, but keep them available in raw).
  const depModuleEdges = aggregateEdges(relations, (nodeId) => moduleIdByNodeId.get(nodeId) ?? null, (rel) => isDependencyRelation(rel.relation))
  const groupEdgesByDirectory = aggregateModuleEdgesToGroups(depModuleEdges.length > 0 ? depModuleEdges : moduleEdges, groupsByDirectory)
  const groupModuleToCommunity = new Map<string, string>()
  for (const group of groupsByCommunity) for (const moduleId of group.moduleIds) groupModuleToCommunity.set(moduleId, group.id)
  const groupEdgesByCommunity = aggregateEdges(relations, (nodeId) => {
    const moduleId = moduleIdByNodeId.get(nodeId)
    return moduleId ? groupModuleToCommunity.get(moduleId) ?? null : null
  }, (rel) => isDependencyRelation(rel.relation))

  const classCount = [...symbolsById.values()].filter((s) => s.kind === "class").length
  const functionCount = symbolsById.size - classCount

  return {
    raw: graph, nodesById, relations, relationsById, outgoing, incoming,
    modulesById, modules, moduleIdByNodeId, symbolsById,
    groupsByDirectory, groupsByCommunity, groupsByExternal, groupsByCoupling,
    moduleEdges: depModuleEdges.length > 0 ? depModuleEdges : moduleEdges,
    groupEdgesByDirectory, groupEdgesByCommunity,
    counts: { modules: modules.length, classes: classCount, functions: functionCount, relations: relations.length, groups: groupsByDirectory.length },
    builtAtCommit: asString(graph.built_at_commit),
  }
}

function isDependencyRelation(relation: string | null): boolean {
  if (relation === null) return false
  if (relation === "contains" || relation === "rationale_for") return false
  return true
}

function buildModules(nodesById: Map<string, NormalizedNode>) {
  const modulesById = new Map<string, CodeModule>()
  const modulesBySource = new Map<string, CodeModule>()
  const moduleIdByNodeId = new Map<string, string>()
  const symbolsById = new Map<string, SymbolNode>()

  function ensureModule(id: string, label: string, sourceFile: string | null, sourceLocation: string | null, raw: GraphifyNode | null, synthetic: boolean): CodeModule {
    const existing = modulesById.get(id)
    if (existing) return existing
    const mod: CodeModule = {
      id, label, sourceFile, sourceLocation,
      directory: directoryOf(sourceFile), groupKey: directoryOf(sourceFile),
      symbolIds: [], classCount: 0, functionCount: 0, inDegree: 0, outDegree: 0, synthetic, raw,
    }
    modulesById.set(id, mod)
    if (sourceFile !== null) modulesBySource.set(sourceFile, mod)
    return mod
  }

  const isModuleNode = (node: NormalizedNode) =>
    node.kind === "module" ||
    (node.fileType === "code" && node.sourceFile !== null && !node.raw._callable && !node.raw._callable_class)

  // Real module/file nodes first.
  for (const node of nodesById.values()) {
    if (!isModuleNode(node)) continue
    if (node.fileType === "concept" || node.fileType === "rationale") continue
    if (node.sourceFile !== null && modulesBySource.has(node.sourceFile)) continue
    ensureModule(node.id, node.label, node.sourceFile, node.sourceLocation, node.raw, false)
    moduleIdByNodeId.set(node.id, node.id)
  }

  for (const node of nodesById.values()) {
    if (node.kind !== "class" && node.kind !== "function") continue
    if (node.sourceFile === null) continue
    let mod = modulesBySource.get(node.sourceFile)
    if (!mod) {
      const label = normalizePath(node.sourceFile).split("/").pop() ?? node.sourceFile
      mod = ensureModule(`module:${node.sourceFile}`, label, node.sourceFile, "L1", null, true)
    }
    moduleIdByNodeId.set(node.id, mod.id)
    mod.symbolIds.push(node.id)
    if (node.kind === "class") mod.classCount += 1
    else mod.functionCount += 1
    symbolsById.set(node.id, {
      id: node.id, label: node.label, kind: node.kind, sourceFile: node.sourceFile,
      sourceLocation: node.sourceLocation, moduleId: mod.id, ownerClassId: null, raw: node.raw,
    })
  }

  const modules = [...modulesById.values()].sort((a, b) => (a.sourceFile ?? a.label).localeCompare(b.sourceFile ?? b.label))
  return { modulesById, modules, moduleIdByNodeId, symbolsById }
}

function computeModuleDegrees(modulesById: Map<string, CodeModule>, moduleIdByNodeId: Map<string, string>, relations: NormalizedRelation[]) {
  for (const rel of relations) {
    if (!isDependencyRelation(rel.relation)) continue
    const sourceModule = moduleIdByNodeId.get(rel.source)
    const targetModule = moduleIdByNodeId.get(rel.target)
    if (!sourceModule || !targetModule || sourceModule === targetModule) continue
    const s = modulesById.get(sourceModule)
    const t = modulesById.get(targetModule)
    if (s) s.outDegree += 1
    if (t) t.inDegree += 1
  }
}

function directoryKey(dir: string, depth: number): string {
  if (dir === "(unknown)" || dir === "(root)") return dir
  const parts = dir.split("/").filter(Boolean)
  return parts.slice(0, Math.max(1, depth)).join("/") || "(root)"
}

export function buildDirectoryGroups(modules: CodeModule[], depth = 1): ModuleGroup[] {
  const byDir = new Map<string, CodeModule[]>()
  for (const mod of modules) {
    const key = directoryKey(mod.groupKey, depth)
    ;(byDir.get(key) ?? byDir.set(key, []).get(key)!).push(mod)
  }
  return [...byDir.entries()]
    .map(([dir, mods]) => ({
      id: `dir${depth}:${dir}`,
      label: dir === "(unknown)" ? "Unknown" : dir,
      kind: "directory" as const,
      evidence: "structural" as const,
      parentId: depth > 1 ? `dir${depth - 1}:${directoryKey(dir, depth - 1)}` : null,
      moduleIds: mods.map((m) => m.id),
      moduleCount: mods.length,
      classCount: mods.reduce((n, m) => n + m.classCount, 0),
      functionCount: mods.reduce((n, m) => n + m.functionCount, 0),
    }))
    .sort((a, b) => b.moduleCount - a.moduleCount || a.label.localeCompare(b.label))
}

function buildCommunityGroups(modules: CodeModule[], nodesById: Map<string, NormalizedNode>): ModuleGroup[] {
  const byCommunity = new Map<string, CodeModule[]>()
  for (const mod of modules) {
    const rawNode = mod.raw ?? (mod.synthetic ? null : nodesById.get(mod.id)?.raw ?? null)
    const community = rawNode && typeof rawNode.community === "number" ? `c${rawNode.community}` : "none"
    ;(byCommunity.get(community) ?? byCommunity.set(community, []).get(community)!).push(mod)
  }
  if (byCommunity.size <= 1) return []
  return [...byCommunity.entries()]
    .map(([community, mods]) => ({
      id: `community:${community}`,
      label: community === "none" ? "No community" : `Community ${community.slice(1)}`,
      kind: "community" as const,
      evidence: "calculated" as const,
      parentId: null,
      moduleIds: mods.map((m) => m.id),
      moduleCount: mods.length,
      classCount: mods.reduce((n, m) => n + m.classCount, 0),
      functionCount: mods.reduce((n, m) => n + m.functionCount, 0),
    }))
    .sort((a, b) => b.moduleCount - a.moduleCount || a.label.localeCompare(b.label))
}

function buildExternalGroups(nodesById: Map<string, NormalizedNode>, relations: NormalizedRelation[], moduleIdByNodeId: Map<string, string>): ModuleGroup[] {
  const externalIds = new Set<string>()
  for (const node of nodesById.values()) {
    if (node.raw.type === "external" || (node.fileType === "concept" && node.raw.type === "external")) externalIds.add(node.id)
    if (node.raw.type === "package" && !node.sourceFile?.startsWith(".")) externalIds.add(node.id)
  }
  const referenced = new Map<string, number>()
  for (const rel of relations) {
    if (!isDependencyRelation(rel.relation)) continue
    for (const end of [rel.source, rel.target]) {
      if (externalIds.has(end) || (!moduleIdByNodeId.has(end) && nodesById.get(end)?.sourceFile == null && nodesById.get(end)?.fileType !== "rationale")) {
        if (nodesById.has(end)) referenced.set(end, (referenced.get(end) ?? 0) + 1)
      }
    }
  }
  const entries = [...referenced.entries()].filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]).slice(0, 120)
  if (entries.length === 0) return []
  return [{
    id: "external:all",
    label: "External dependencies",
    kind: "external",
    evidence: "structural",
    parentId: null,
    moduleIds: entries.map(([id]) => id),
    moduleCount: entries.length,
    classCount: 0,
    functionCount: 0,
  }]
}

function buildCouplingGroups(modules: CodeModule[]): ModuleGroup[] {
  if (modules.length === 0) return []
  const scored = modules.map((m) => ({ m, score: m.inDegree + m.outDegree }))
  scored.sort((a, b) => b.score - a.score)
  const highCut = Math.max(1, Math.floor(scored.length * 0.2))
  const midCut = Math.max(highCut + 1, Math.floor(scored.length * 0.6))
  const buckets: Array<[string, typeof scored]> = [
    ["coupling:high", scored.slice(0, highCut)],
    ["coupling:medium", scored.slice(highCut, midCut)],
    ["coupling:low", scored.slice(midCut)],
  ]
  return buckets.filter(([, items]) => items.length > 0).map(([id, items]) => ({
    id,
    label: id.endsWith("high") ? "High coupling" : id.endsWith("medium") ? "Medium coupling" : "Low coupling",
    kind: "coupling" as const,
    evidence: "calculated" as const,
    parentId: null,
    moduleIds: items.map((i) => i.m.id),
    moduleCount: items.length,
    classCount: items.reduce((n, i) => n + i.m.classCount, 0),
    functionCount: items.reduce((n, i) => n + i.m.functionCount, 0),
  }))
}

function aggregateEdges(
  relations: NormalizedRelation[],
  resolveGroup: (nodeId: string) => string | null,
  include: (rel: NormalizedRelation) => boolean,
): AggregatedEdge[] {
  const map = new Map<string, AggregatedEdge>()
  for (const rel of relations) {
    if (!include(rel)) continue
    const source = resolveGroup(rel.source)
    const target = resolveGroup(rel.target)
    if (!source || !target || source === target) continue
    const key = `${source}\u0000${target}\u0000${rel.relation ?? ""}`
    const existing = map.get(key)
    if (existing) {
      existing.weight += 1
      existing.originalRelationIds.push(rel.id)
    } else {
      map.set(key, { id: `agg:${key}`, source, target, weight: 1, relations: rel.relation ? [rel.relation] : [], originalRelationIds: [rel.id] })
    }
  }
  return [...map.values()].sort((a, b) => b.weight - a.weight)
}

/** Aggregates module-level edges into the active groups (works for any perspective/depth). */
export function aggregateModuleEdgesToGroups(moduleEdges: AggregatedEdge[], groups: ModuleGroup[], includeSelf = false): AggregatedEdge[] {
  const moduleToGroup = new Map<string, string>()
  for (const group of groups) for (const moduleId of group.moduleIds) moduleToGroup.set(moduleId, group.id)
  const map = new Map<string, AggregatedEdge>()
  for (const edge of moduleEdges) {
    const source = moduleToGroup.get(edge.source)
    const target = moduleToGroup.get(edge.target)
    if (!source || !target) continue
    if (source === target && !includeSelf) continue
    const relKey = edge.relations.join("|")
    const key = `${source}\u0000${target}\u0000${relKey}`
    const existing = map.get(key)
    if (existing) {
      existing.weight += edge.weight
      existing.originalRelationIds.push(...edge.originalRelationIds)
      for (const r of edge.relations) if (!existing.relations.includes(r)) existing.relations.push(r)
    } else {
      map.set(key, { id: `gagg:${key}`, source, target, weight: edge.weight, relations: [...edge.relations], originalRelationIds: [...edge.originalRelationIds] })
    }
  }
  return [...map.values()].sort((a, b) => b.weight - a.weight)
}

export function traverseImpact(index: ArchitectureIndex, centerId: string, depth: number): ImpactGraph {
  const maxDepth = Math.max(1, Math.min(3, Math.floor(depth)))
  const nodeIds = new Set<string>([centerId])
  const relationIds = new Set<string>()
  const hits = new Map<string, ImpactHit>()

  type Step = { nodeId: string; depth: number; direction: "out" | "in"; via: string[] }
  const queue: Step[] = [
    { nodeId: centerId, depth: 0, direction: "out", via: [] },
    { nodeId: centerId, depth: 0, direction: "in", via: [] },
  ]
  const seen = new Set<string>([`out:${centerId}:0`, `in:${centerId}:0`])

  while (queue.length > 0) {
    const step = queue.shift()!
    if (step.depth >= maxDepth) continue
    const edges = step.direction === "out" ? index.outgoing.get(step.nodeId) ?? [] : index.incoming.get(step.nodeId) ?? []
    for (const rel of edges) {
      if (rel.relation === "rationale_for") continue
      const nextId = step.direction === "out" ? rel.target : rel.source
      const nextDepth = step.depth + 1
      const key = `${step.direction}:${nextId}:${nextDepth}`
      const via = [...step.via, rel.id]
      relationIds.add(rel.id)
      nodeIds.add(nextId)
      const existing = hits.get(nextId)
      if (!existing || nextDepth < existing.depth) {
        hits.set(nextId, { nodeId: nextId, depth: nextDepth, direction: step.direction, viaRelationIds: via, observed: nextDepth === 1 })
      }
      if (!seen.has(key)) {
        seen.add(key)
        queue.push({ nodeId: nextId, depth: nextDepth, direction: step.direction, via })
      }
    }
  }
  return { centerId, depth: maxDepth, nodeIds, hits, relationIds }
}

/** Resolve a node's containing module id from the index. */
export function moduleOf(index: ArchitectureIndex, nodeId: string): string | null {
  return index.moduleIdByNodeId.get(nodeId) ?? (index.modulesById.has(nodeId) ? nodeId : null)
}

/**
 * Normalizes the Graphify artifact into a compact, renderable structural graph.
 *
 * Graphify nodes carry their own type markers:
 * - `_callable_class` marks a class.
 * - `_callable` (without `_callable_class`) marks a function or method.
 * - file/module nodes are identified by their id matching the normalized
 *   source path (or by an explicit `type: "module" | "package"`).
 *
 * Everything else (rationale, concept, external packages) is not part of the
 * structural view, although its links still contribute to module-level edges.
 */

export type GraphNodeKind = "module" | "class" | "function" | "other"

export interface GraphifyNode {
  id: string
  label?: string
  type?: string
  file_type?: string
  source_file?: string
  source_location?: string
  _callable?: boolean
  _callable_class?: boolean
  [key: string]: unknown
}

export interface GraphifyLink {
  source: string
  target: string
  relation?: string
  weight?: number
  [key: string]: unknown
}

export interface GraphifyGraph {
  nodes?: GraphifyNode[]
  links?: GraphifyLink[]
  edges?: GraphifyLink[]
  built_at_commit?: string
  [key: string]: unknown
}

export interface GraphNode {
  id: string
  label: string
  kind: GraphNodeKind
  sourceFile: string | null
  sourceLocation: string | null
  moduleId: string | null
  degree: number
  x: number
  y: number
  radius: number
}

export interface GraphModule {
  id: string
  node: GraphNode
  children: GraphNode[]
  x: number
  y: number
  width: number
  height: number
}

export interface GraphEdge {
  source: string
  target: string
  relation: string | null
  weight: number
  kind: "intra" | "inter"
}

export interface GraphBounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export interface StructuralGraphModel {
  modules: GraphModule[]
  nodes: GraphNode[]
  moduleById: Map<string, GraphModule>
  nodeById: Map<string, GraphNode>
  edges: GraphEdge[]
  bounds: GraphBounds
  counts: { modules: number; classes: number; functions: number }
}

const MODULE_RADIUS = 7
const CLASS_RADIUS = 4.5
const FUNCTION_RADIUS = 3.5
const CLUSTER_GAP = 10
const CLUSTER_PADDING = 12
const CLUSTER_HEADER = 20
const CHILD_SPACING = 16

/** Matches the id Graphify assigns to a file node (path without extension). */
export function moduleIdFor(sourceFile: string): string {
  return sourceFile
    .replace(/\.[^./\\]+$/, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
}

export function classifyGraphNode(node: GraphifyNode): GraphNodeKind {
  if (node._callable_class === true || node.type === "class") return "class"
  if (node._callable === true || node.type === "function" || node.type === "method") return "function"
  if (node.type === "module" || node.type === "package" || node.type === "file") return "module"
  if (typeof node.source_file === "string" && node.source_file !== "" && node.id === moduleIdFor(node.source_file)) {
    return "module"
  }
  return "other"
}

function isRawNode(value: unknown): value is GraphifyNode {
  return typeof value === "object" && value !== null && typeof (value as { id?: unknown }).id === "string"
}

function isRawLink(value: unknown): value is GraphifyLink {
  return typeof value === "object" && value !== null
    && typeof (value as { source?: unknown }).source === "string"
    && typeof (value as { target?: unknown }).target === "string"
}

function sourceFileOf(node: GraphifyNode): string | null {
  return typeof node.source_file === "string" && node.source_file !== "" ? node.source_file : null
}

function labelOf(node: GraphifyNode, sourceFile: string | null): string {
  if (typeof node.label === "string" && node.label !== "") return node.label
  if (sourceFile !== null) return sourceFile.split(/[\\/]/).pop() ?? sourceFile
  return node.id
}

export function buildStructuralGraph(graph: GraphifyGraph): StructuralGraphModel {
  if (typeof graph !== "object" || graph === null || !Array.isArray(graph.nodes)) {
    throw new Error("Invalid structural graph")
  }

  const rawNodes = graph.nodes.filter(isRawNode)
  const rawLinks = (Array.isArray(graph.links) ? graph.links : Array.isArray(graph.edges) ? graph.edges : []).filter(isRawLink)
  const rawById = new Map(rawNodes.map((node) => [node.id, node]))
  const modules: GraphModule[] = []
  const modulesBySource = new Map<string, GraphModule>()
  const nodeById = new Map<string, GraphNode>()
  const counts = { modules: 0, classes: 0, functions: 0 }

  function createModule(raw: GraphifyNode, sourceFile: string | null): GraphModule {
    const node: GraphNode = {
      id: raw.id,
      label: labelOf(raw, sourceFile),
      kind: "module",
      sourceFile,
      sourceLocation: typeof raw.source_location === "string" ? raw.source_location : null,
      moduleId: raw.id,
      degree: 0,
      x: 0,
      y: 0,
      radius: MODULE_RADIUS,
    }
    const module: GraphModule = { id: raw.id, node, children: [], x: 0, y: 0, width: 0, height: 0 }
    modules.push(module)
    nodeById.set(node.id, node)
    if (sourceFile !== null) modulesBySource.set(sourceFile, module)
    counts.modules += 1
    return module
  }

  // Real module/file nodes first, so callables can attach to them.
  for (const raw of rawNodes) {
    if (classifyGraphNode(raw) !== "module") continue
    const sourceFile = sourceFileOf(raw)
    if (sourceFile !== null && modulesBySource.has(sourceFile)) continue
    createModule(raw, sourceFile)
  }

  function moduleFor(sourceFile: string): GraphModule {
    const existing = modulesBySource.get(sourceFile)
    if (existing !== undefined) return existing
    const label = sourceFile.split(/[\\/]/).pop() ?? sourceFile
    const module = createModule({ id: `module:${sourceFile}`, label, source_file: sourceFile, source_location: "L1" }, sourceFile)
    return module
  }

  for (const raw of rawNodes) {
    const kind = classifyGraphNode(raw)
    if (kind !== "class" && kind !== "function") continue
    const sourceFile = sourceFileOf(raw)
    if (sourceFile === null) continue
    const module = moduleFor(sourceFile)
    const node: GraphNode = {
      id: raw.id,
      label: labelOf(raw, sourceFile),
      kind,
      sourceFile,
      sourceLocation: typeof raw.source_location === "string" ? raw.source_location : null,
      moduleId: module.id,
      degree: 0,
      x: 0,
      y: 0,
      radius: kind === "class" ? CLASS_RADIUS : FUNCTION_RADIUS,
    }
    module.children.push(node)
    nodeById.set(node.id, node)
    counts[kind === "class" ? "classes" : "functions"] += 1
  }

  layoutModules(modules)

  function moduleIdForRaw(raw: GraphifyNode): string | null {
    const direct = nodeById.get(raw.id)
    if (direct !== undefined && direct.kind === "module") return direct.id
    const sourceFile = sourceFileOf(raw)
    if (sourceFile === null) return null
    return modulesBySource.get(sourceFile)?.id ?? null
  }

  const edges: GraphEdge[] = []
  const aggregated = new Map<string, { source: string; target: string; relation: string | null; weight: number }>()

  for (const raw of rawLinks) {
    const sourceRaw = rawById.get(raw.source)
    const targetRaw = rawById.get(raw.target)
    if (sourceRaw === undefined || targetRaw === undefined) continue
    const sourceModule = moduleIdForRaw(sourceRaw)
    const targetModule = moduleIdForRaw(targetRaw)
    if (sourceModule === null || targetModule === null) continue

    if (sourceModule === targetModule) {
      const source = nodeById.get(sourceRaw.id)
      const target = nodeById.get(targetRaw.id)
      if (source === undefined || target === undefined || source.id === target.id) continue
      edges.push({ source: source.id, target: target.id, relation: raw.relation ?? null, weight: 1, kind: "intra" })
      source.degree += 1
      target.degree += 1
      continue
    }

    const key = sourceModule < targetModule ? `${sourceModule}\u0000${targetModule}` : `${targetModule}\u0000${sourceModule}`
    const sourceVisible = nodeById.get(sourceRaw.id)
    const targetVisible = nodeById.get(targetRaw.id)
    if (sourceVisible !== undefined && sourceVisible.kind !== "module") sourceVisible.degree += 1
    if (targetVisible !== undefined && targetVisible.kind !== "module") targetVisible.degree += 1
    const current = aggregated.get(key)
    if (current === undefined) {
      aggregated.set(key, { source: sourceModule, target: targetModule, relation: raw.relation ?? null, weight: 1 })
    } else {
      current.weight += 1
    }
  }

  const moduleById = new Map(modules.map((module) => [module.id, module]))
  for (const edge of aggregated.values()) {
    edges.push({ source: edge.source, target: edge.target, relation: edge.relation, weight: edge.weight, kind: "inter" })
    const source = moduleById.get(edge.source)
    const target = moduleById.get(edge.target)
    if (source !== undefined) source.node.degree += edge.weight
    if (target !== undefined) target.node.degree += edge.weight
  }

  const bounds = moduleBounds(modules)
  const nodes = [...modules.map((module) => module.node), ...modules.flatMap((module) => module.children)]

  return { modules, nodes, moduleById, nodeById, edges, bounds, counts }
}

function layoutModules(modules: GraphModule[]): void {
  modules.sort((left, right) => {
    const leftKey = left.node.sourceFile ?? left.node.label
    const rightKey = right.node.sourceFile ?? right.node.label
    return leftKey.localeCompare(rightKey)
  })

  const totalArea = modules.reduce((area, module) => {
    const children = module.children.length
    const columns = Math.max(1, Math.ceil(Math.sqrt(children)))
    const rows = Math.max(1, Math.ceil(children / columns))
    return area + (columns * CHILD_SPACING + CLUSTER_PADDING * 2) * (CLUSTER_HEADER + rows * CHILD_SPACING + CLUSTER_PADDING)
  }, 0)
  const targetWidth = Math.max(1000, Math.sqrt(totalArea) * 1.5)

  let x = 0
  let y = 0
  let rowHeight = 0

  for (const module of modules) {
    const children = module.children.length
    const columns = Math.max(1, Math.ceil(Math.sqrt(children)))
    const rows = Math.max(1, Math.ceil(children / columns))
    module.width = Math.max(76, columns * CHILD_SPACING + CLUSTER_PADDING * 2)
    module.height = Math.max(64, CLUSTER_HEADER + rows * CHILD_SPACING + CLUSTER_PADDING)

    if (x > 0 && x + module.width > targetWidth) {
      x = 0
      y += rowHeight + CLUSTER_GAP
      rowHeight = 0
    }
    module.x = x
    module.y = y
    x += module.width + CLUSTER_GAP
    rowHeight = Math.max(rowHeight, module.height)

    module.node.x = module.x + CLUSTER_PADDING + 8
    module.node.y = module.y + CLUSTER_PADDING + 6

    const startX = module.x + CLUSTER_PADDING + 8
    const startY = module.y + CLUSTER_HEADER + CLUSTER_PADDING + 4
    module.children.forEach((child, index) => {
      child.x = startX + (index % columns) * CHILD_SPACING
      child.y = startY + Math.floor(index / columns) * CHILD_SPACING
    })
  }
}

function moduleBounds(modules: GraphModule[]): GraphBounds {
  if (modules.length === 0) return { minX: 0, minY: 0, maxX: 1, maxY: 1 }
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const module of modules) {
    minX = Math.min(minX, module.x)
    minY = Math.min(minY, module.y)
    maxX = Math.max(maxX, module.x + module.width)
    maxY = Math.max(maxY, module.y + module.height)
  }
  return { minX, minY, maxX, maxY }
}

import { describe, expect, it } from "vitest"
import { aggregateModuleEdgesToGroups, buildArchitectureIndex, buildDirectoryGroups, moduleIdFor, traverseImpact, type GraphifyGraph } from "./graphAdapter.ts"
import { detectCycleCount } from "./explorerLayout.ts"

const realShape: GraphifyGraph = {
  directed: false,
  multigraph: false,
  graph: { schema_version: 1, graphify_version: "0.9.100" },
  nodes: [
    { id: moduleIdFor("pkg/a.ts"), label: "a.ts", file_type: "code", source_file: "pkg/a.ts", source_location: "L1", community: 1 },
    { id: "pkg_a_class", label: "ClassA", _callable: true, _callable_class: true, file_type: "code", source_file: "pkg/a.ts", source_location: "L5", community: 1 },
    { id: "pkg_a_run", label: "runA()", _callable: true, file_type: "code", source_file: "pkg/a.ts", source_location: "L20", community: 1 },
    { id: moduleIdFor("pkg/b.ts"), label: "b.ts", file_type: "code", source_file: "pkg/b.ts", source_location: "L1", community: 2 },
    { id: "pkg_b_run", label: "runB()", _callable: true, file_type: "code", source_file: "pkg/b.ts", source_location: "L8", community: 2 },
    { id: "iso_runc", label: "runC()", _callable: true, file_type: "code", source_file: "iso/c.ts", source_location: "L3" },
    { id: "concept_x", label: "note", file_type: "concept", source_file: "docs/n.md", source_location: "L1" },
  ],
  links: [
    { source: moduleIdFor("pkg/a.ts"), target: "pkg_a_class", relation: "contains", _origin: "ast", confidence: "EXTRACTED", confidence_score: 1, source_file: "pkg/a.ts", source_location: "L5", weight: 1 },
    { source: "pkg_a_class", target: "pkg_a_run", relation: "method", _origin: "ast", confidence: "EXTRACTED", weight: 1 },
    { source: "pkg_a_run", target: "pkg_b_run", relation: "calls", _origin: "ast", confidence: "INFERRED", confidence_score: 0.95, source_file: "pkg/a.ts", source_location: "L22", weight: 0.8, context: "call" },
    { source: moduleIdFor("pkg/b.ts"), target: moduleIdFor("pkg/a.ts"), relation: "imports_from", _origin: "ast", confidence: "EXTRACTED", weight: 1 },
    { source: "pkg_a_run", target: "iso_runc", relation: "calls" },
  ],
  hyperedges: [],
  built_at_commit: "abc1234",
} as GraphifyGraph

describe("architecture graph adapter", () => {
  it("reads the real Graphify JSON shape and preserves original data", () => {
    const index = buildArchitectureIndex(realShape)
    expect(index.builtAtCommit).toBe("abc1234")
    expect(index.nodesById.size).toBe(7)
    expect(index.relations).toHaveLength(5)
    expect(index.relationsById.get(index.relations[2]!.id)?.raw).toMatchObject({ relation: "calls", confidence: "INFERRED", context: "call" })
    expect(index.nodesById.get("pkg_a_class")?.raw._callable_class).toBe(true)
    expect(index.counts.modules).toBeGreaterThanOrEqual(3)
    expect(index.counts.classes).toBe(1)
    expect(index.counts.functions).toBe(3)
  })

  it("preserves IDs and never invents relations", () => {
    const index = buildArchitectureIndex(realShape)
    expect(index.nodesById.has("pkg_a_run")).toBe(true)
    for (const rel of index.relations) {
      expect(index.nodesById.has(rel.source)).toBe(true)
      expect(index.nodesById.has(rel.target)).toBe(true)
      expect(rel.raw.source).toBe(rel.source)
      expect(rel.raw.target).toBe(rel.target)
    }
  })

  it("builds module hierarchy and synthetic modules for missing file nodes", () => {
    const index = buildArchitectureIndex(realShape)
    expect(index.moduleIdByNodeId.get("pkg_a_run")).toBe(moduleIdFor("pkg/a.ts"))
    expect(index.moduleIdByNodeId.get("iso_runc")).toMatch(/^module:|iso/)
    const isoModule = [...index.modulesById.values()].find((m) => m.sourceFile === "iso/c.ts")
    expect(isoModule?.symbolIds).toContain("iso_runc")
    expect(isoModule?.synthetic).toBe(true)
  })

  it("aggregates module dependencies with traceability to original relations", () => {
    const index = buildArchitectureIndex(realShape)
    const aId = moduleIdFor("pkg/a.ts"), bId = moduleIdFor("pkg/b.ts")
    const dep = index.moduleEdges.find((e) => (e.source === aId && e.target === bId) || (e.source === bId && e.target === aId))
    expect(dep).toBeDefined()
    expect(dep!.weight).toBeGreaterThanOrEqual(1)
    expect(dep!.originalRelationIds.length).toBe(dep!.weight)
  })

  it("maps module edges to active directory groups at different depths (System Overview)", () => {
    const index = buildArchitectureIndex(realShape)
    const depth1 = buildDirectoryGroups(index.modules, 1)
    const edges1 = aggregateModuleEdgesToGroups(index.moduleEdges, depth1)
    expect(edges1.some((e) => depth1.some((g) => g.id === e.source) && depth1.some((g) => g.id === e.target))).toBe(true)
    const depth2 = buildDirectoryGroups(index.modules, 2)
    const edges2 = aggregateModuleEdgesToGroups(index.moduleEdges, depth2)
    for (const edge of [...edges1, ...edges2]) {
      expect(edge.source.startsWith("dir") || edge.source.includes(":")).toBe(true)
      expect(edge.originalRelationIds.length).toBeGreaterThanOrEqual(edge.weight)
    }
  })

  it("computes incoming/outgoing module degrees from dependency relations", () => {
    const index = buildArchitectureIndex(realShape)
    const a = index.modulesById.get(moduleIdFor("pkg/a.ts"))!
    const b = index.modulesById.get(moduleIdFor("pkg/b.ts"))!
    expect(a.outDegree + a.inDegree).toBeGreaterThan(0)
    expect(b.outDegree + b.inDegree).toBeGreaterThan(0)
  })

  it("groups modules by directories (structural) and communities (computed) when available", () => {
    const index = buildArchitectureIndex(realShape)
    expect(index.groupsByDirectory.length).toBeGreaterThan(0)
    expect(index.groupsByDirectory.every((g) => g.kind === "directory")).toBe(true)
    expect(index.groupsByCommunity.every((g) => g.kind === "community")).toBe(true)
    const allModules = index.groupsByDirectory.flatMap((g) => g.moduleIds)
    expect(new Set(allModules).size).toBe(index.modules.length)
  })

  it("traverses impact with configurable depth and separates directions", () => {
    const index = buildArchitectureIndex(realShape)
    const d1 = traverseImpact(index, "pkg_a_run", 1)
    expect(d1.nodeIds.has("pkg_a_run")).toBe(true)
    expect(d1.nodeIds.has("pkg_b_run")).toBe(true)
    expect(d1.hits.get("pkg_b_run")?.depth).toBe(1)
    expect(d1.hits.get("pkg_b_run")?.observed).toBe(true)
    const d2 = traverseImpact(index, "pkg_b_mod", 2)
    expect(d2.depth).toBe(2)
  })

  it("handles isolated nodes and incomplete data", () => {
    const index = buildArchitectureIndex({
      nodes: [{ id: "lonely", file_type: "code", source_file: "lonely.ts", source_location: "L1" }, { id: "bad" } as never],
      links: [{ source: "lonely", target: "missing", relation: "calls" }],
    })
    expect(index.nodesById.has("lonely")).toBe(true)
    expect(index.relations).toHaveLength(0)
    expect(index.modules.length).toBeGreaterThanOrEqual(1)
  })

  it("detects cycles and accepts graphs with cycles", () => {
    const count = detectCycleCount(["a", "b", "c"], [{ source: "a", target: "b" }, { source: "b", target: "c" }, { source: "c", target: "a" }])
    expect(count).toBeGreaterThan(0)
    const aId = moduleIdFor("a.ts"), bId = moduleIdFor("b.ts")
    const index = buildArchitectureIndex({
      nodes: [
        { id: aId, label: "a.ts", file_type: "code", source_file: "a.ts", source_location: "L1" },
        { id: bId, label: "b.ts", file_type: "code", source_file: "b.ts", source_location: "L1" },
      ],
      links: [{ source: aId, target: bId, relation: "imports" }, { source: bId, target: aId, relation: "imports" }],
    })
    expect(index.moduleEdges.length).toBeGreaterThan(0)
  })

  it("rejects payloads that are not graph artifacts", () => {
    expect(() => buildArchitectureIndex({} as GraphifyGraph)).toThrow("Invalid structural graph")
    expect(() => buildArchitectureIndex(null as unknown as GraphifyGraph)).toThrow("Invalid structural graph")
  })

  it("keeps moduleIdFor compatible with Graphify-style IDs", () => {
    expect(moduleIdFor("frontend/src/features/project-management/GraphView.tsx")).toBe("frontend_src_features_project_management_graphview")
  })
})

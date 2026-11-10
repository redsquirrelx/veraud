import { describe, expect, it } from "vitest"
import { buildStructuralGraph, classifyGraphNode, moduleIdFor, type GraphifyGraph } from "./structuralGraphModel.ts"

const graph: GraphifyGraph = {
  nodes: [
    { id: "src_a", label: "a.ts", source_file: "src/a.ts", source_location: "L1" },
    { id: "src_a_classa", label: "ClassA", _callable: true, _callable_class: true, source_file: "src/a.ts", source_location: "L5" },
    { id: "src_a_runa", label: "runA", _callable: true, source_file: "src/a.ts", source_location: "L20" },
    { id: "src_b", label: "b.ts", source_file: "src/b.ts", source_location: "L1" },
    { id: "src_b_runb", label: "runB", _callable: true, source_file: "src/b.ts", source_location: "L8" },
    { id: "src_c_runc", label: "runC", _callable: true, source_file: "src/c.ts", source_location: "L3" },
    { id: "mermaid", label: "mermaid", type: "module" },
    { id: "external_pkg", label: "external", type: "external" },
    { id: "concept_note", label: "note", file_type: "concept" },
  ],
  links: [
    { source: "src_a_classa", target: "src_a_runa", relation: "calls" },
    { source: "src_a_runa", target: "src_b_runb", relation: "calls" },
    { source: "src_b", target: "src_b_runb", relation: "contains" },
    { source: "src_a_runa", target: "src_c_runc", relation: "calls" },
    { source: "src_c_runc", target: "external_pkg", relation: "uses" },
    { source: "src_a", target: "src_b", relation: "imports" },
    { source: "src_a_runa", target: "src_a_runa", relation: "calls" },
  ],
}

describe("structural graph model", () => {
  it("classifies graphify nodes from their real markers", () => {
    expect(classifyGraphNode({ id: "src_a", source_file: "src/a.ts" })).toBe("module")
    expect(classifyGraphNode({ id: "pkg", type: "package" })).toBe("module")
    expect(classifyGraphNode({ id: "lib", type: "module" })).toBe("module")
    expect(classifyGraphNode({ id: "src_a_class", _callable: true, _callable_class: true })).toBe("class")
    expect(classifyGraphNode({ id: "typed_class", type: "class" })).toBe("class")
    expect(classifyGraphNode({ id: "src_a_run", _callable: true })).toBe("function")
    expect(classifyGraphNode({ id: "typed_function", type: "function" })).toBe("function")
    expect(classifyGraphNode({ id: "external", type: "external" })).toBe("other")
    expect(classifyGraphNode({ id: "note", file_type: "concept" })).toBe("other")
    expect(moduleIdFor("src/features/MyFile.tsx")).toBe("src_features_myfile")
  })

  it("builds modules, classes and functions with synthetic modules for missing files", () => {
    const model = buildStructuralGraph(graph)
    expect(model.counts).toEqual({ modules: 4, classes: 1, functions: 3 })
    expect(model.modules.map((module) => module.id)).toEqual(expect.arrayContaining(["src_a", "src_b", "mermaid", "module:src/c.ts"]))
    expect(model.moduleById.get("src_a")?.children.map((child) => child.id)).toEqual(["src_a_classa", "src_a_runa"])
    expect(model.moduleById.get("module:src/c.ts")?.children.map((child) => child.id)).toEqual(["src_c_runc"])
    expect(model.moduleById.get("mermaid")?.children).toEqual([])
    expect(model.nodeById.has("external_pkg")).toBe(false)
    expect(model.nodeById.has("concept_note")).toBe(false)
  })

  it("aggregates cross-module relations and keeps intra-module relations node to node", () => {
    const model = buildStructuralGraph(graph)
    const inter = model.edges.filter((edge) => edge.kind === "inter")
    const intra = model.edges.filter((edge) => edge.kind === "intra")
    expect(inter).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "src_a", target: "src_b", weight: 2 }),
      expect.objectContaining({ source: "src_a", target: "module:src/c.ts", weight: 1 }),
    ]))
    expect(intra).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "src_a_classa", target: "src_a_runa" }),
      expect.objectContaining({ source: "src_b", target: "src_b_runb" }),
    ]))
    expect(intra.some((edge) => edge.source === edge.target)).toBe(false)
    expect(model.moduleById.get("src_a")?.node.degree).toBe(3)
  })

  it("lays every node inside its module cluster and produces finite bounds", () => {
    const model = buildStructuralGraph(graph)
    for (const module of model.modules) {
      for (const node of [module.node, ...module.children]) {
        expect(Number.isFinite(node.x)).toBe(true)
        expect(Number.isFinite(node.y)).toBe(true)
        expect(node.x).toBeGreaterThanOrEqual(module.x)
        expect(node.x).toBeLessThanOrEqual(module.x + module.width)
        expect(node.y).toBeGreaterThanOrEqual(module.y)
        expect(node.y).toBeLessThanOrEqual(module.y + module.height)
      }
    }
    expect(model.bounds.maxX).toBeGreaterThan(model.bounds.minX)
    expect(model.bounds.maxY).toBeGreaterThan(model.bounds.minY)
    expect(Number.isFinite(model.bounds.maxX)).toBe(true)
    expect(Number.isFinite(model.bounds.maxY)).toBe(true)
  })

  it("rejects payloads that are not graph artifacts", () => {
    expect(() => buildStructuralGraph({} as GraphifyGraph)).toThrow("Invalid structural graph")
    expect(() => buildStructuralGraph(null as unknown as GraphifyGraph)).toThrow("Invalid structural graph")
  })
})

import { expect, it } from "vitest"
import { readAgentEvidence } from "./auditAgentEvidence.ts"

const evidence = { id: "E-1", source: "src/service.ts", file_id: "file:1", symbol_ids: ["symbol:1"],
  provenance: { agent_id: "investigator", invocation_id: "inv-1" } }
const read = (extra: Record<string, unknown>) => readAgentEvidence({
  evidence_inventory: [evidence], executions: [{ agent_id: "investigator", invocation_id: "inv-1" }], ...extra,
}, "inv-1")!.evidence[0].symbols![0]

it("uses audit-wide symbol metadata and resolves file IDs without adding other agents' evidence", () => {
  const data = { executions: [
    { agent_id: "investigator", invocation_id: "inv-1", recorded_results: { symbols: [{ id: "symbol:1", name: "Service.run" }] } },
    { agent_id: "repository_analysis", invocation_id: "repo-1", recorded_results: {
      entity_catalog: [{ id: "file:1", kind: "file", path: "src/service.ts" },
        { id: "symbol:1", kind: "symbol", file_id: "file:1", name: "Service.run", start_line: 20, end_line: 22 }],
    } },
  ], evidence_inventory: [evidence, { ...evidence, id: "foreign", provenance: { agent_id: "other", invocation_id: "other-1" } }] }
  const result = readAgentEvidence(data, "inv-1")!
  expect(result.evidence).toHaveLength(1)
  expect(result.evidence[0].symbols![0]).toMatchObject({ name: "Service.run", kind: null, source: "src/service.ts", startLine: 20, endLine: 22 })
})

it("reads explicit canonical reference-label coordinates, without guessing symbol kinds", () => {
  expect(read({ reference_labels: { "symbol:1": "Service.run — src/service.ts:20–22" } }))
    .toMatchObject({ name: "Service.run", kind: null, source: "src/service.ts", startLine: 20, endLine: 22 })
})

it("reads structured symbol metadata retained as tool results", () => {
  expect(read({ metrics_and_tool_results: [{ result: { symbols: [{ symbol_id: "symbol:1", symbol_name: "Service.run",
    kind: "method", file_id: "file:1", start_line: 20, end_line: 22 }] } }] }))
    .toMatchObject({ name: "Service.run", kind: "method", source: "src/service.ts", startLine: 20, endLine: 22 })
})

it.each(["Service.run", "Service.run — src/service.ts", "Service.run — src/service.ts:22–20", "Service.run — https://example.test:20–22"])(
  "does not invent coordinates for an unresolved label: %s", (label) => {
    expect(read({ reference_labels: { "symbol:1": label } })).toMatchObject({ startLine: null, endLine: null, source: null })
  },
)

it("does not use reference labels to override conflicting structured declarations", () => {
  expect(read({ executions: [{ agent_id: "investigator", invocation_id: "inv-1", recorded_results: { symbols: [
    { id: "symbol:1", name: "First", start_line: 20, end_line: 22 },
    { id: "symbol:1", name: "Second", start_line: 30, end_line: 32 },
  ] } }], reference_labels: { "symbol:1": "First — src/service.ts:20–22" } }))
    .toMatchObject({ name: null, startLine: null, endLine: null })
})

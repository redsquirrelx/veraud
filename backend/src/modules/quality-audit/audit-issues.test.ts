import { it } from "node:test"
import assert from "node:assert/strict"
import { mkdtemp, writeFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { readAuditIssues, projectAuditIssues } from "./audit-issues.js"

async function fixture(text: string, run: (path: string) => Promise<void>) {
  const root = await mkdtemp(join(tmpdir(), "audit-issues-"))
  try {
    const path = join(root, "annexes.json")
    await writeFile(path, text)
    await run(path)
  } finally { await rm(root, { recursive: true, force: true }) }
}

it("extracts incidents after a large nested inventory without retaining it", async () => {
  const issues = [{ agent_id: "test_isolation", termination_reason: "provider_daily_quota_exhausted",
    explanation: "Cuota diaria agotada", incidents: ["HTTP 429"], diagnostics: ['quoted: " } ] \\'] }]
  const text = JSON.stringify({ inventory: Array.from({ length: 10000 }, () => ({
    execution_issues: ["not the root property"], content: 'escaped \\ " { : , } é',
  })), execution_issues: issues, tail: [] })
  await fixture(text, async (path) => assert.deepEqual(await readAuditIssues(path), issues))
})

it("handles escaped top-level keys, primitive siblings and missing incidents", async () => {
  await fixture('{"first":null,"second":2,"execution_\\u0069ssues":[{"agent_id":"a"}],"last":true}',
    async (path) => assert.deepEqual(await readAuditIssues(path), [{ agent_id: "a" }]))
  await fixture('{"other":{"execution_issues":[1]}}', async (path) => assert.deepEqual(await readAuditIssues(path), []))
  await fixture('{"execution_issues":null}', async (path) => assert.deepEqual(await readAuditIssues(path), []))
})

it("stops reading once incidents are available and rejects oversized incident payloads", async () => {
  await fixture('{"execution_issues":[1],"unread tail":', async (path) => assert.deepEqual(await readAuditIssues(path), [1]))
  await fixture(JSON.stringify({ execution_issues: ["x".repeat(1_048_577)] }),
    async (path) => assert.rejects(readAuditIssues(path), /exceeds/))
})

it("projects only incident metadata, never evidence or arbitrary producer fields", () => {
  const result = projectAuditIssues([{ agent_id: "a", evidence_inventory: ["private source"],
    incidents: ["HTTP 429", 2], diagnostics: ["quota"], explanation: "Quota exhausted" }])
  assert.equal(JSON.stringify(result).includes("private source"), false)
  assert.deepEqual(result[0]?.incidents, ["HTTP 429"])
  assert.deepEqual(projectAuditIssues(null), [])
})

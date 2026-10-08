import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { InvalidDirectInputError, assertDirectCheckout, sanitizeDirectInput } from "./direct-input.guard.js"
import { WorkspaceMissingError } from "./agent-target.resolver.js"

describe("direct input guard", () => {
  it("passes inputs without root_path through untouched", () => {
    const input = { code: "print(1)", evaluated_attribute: "maintainability" }
    assert.equal(sanitizeDirectInput(input, "/ws"), input)
  })

  it("resolves a relative root_path inside the workspace", () => {
    const workspace = mkdtempSync(join(tmpdir(), "veraud-guard-"))
    const out = sanitizeDirectInput({ root_path: "proj" }, workspace)

    assert.equal(out["root_path"], join(workspace, "proj"))
  })

  it("rejects traversal outside the workspace", () => {
    const workspace = mkdtempSync(join(tmpdir(), "veraud-guard-"))

    assert.throws(() => sanitizeDirectInput({ root_path: "../evil" }, workspace), InvalidDirectInputError)
    assert.throws(() => sanitizeDirectInput({ root_path: ".." }, workspace), InvalidDirectInputError)
    assert.throws(() => sanitizeDirectInput({ root_path: "" }, workspace), InvalidDirectInputError)
    assert.throws(() => sanitizeDirectInput({ root_path: 42 as unknown as string }, workspace), InvalidDirectInputError)
  })

  it("rejects a sibling sharing a string prefix with the workspace", () => {
    const workspace = mkdtempSync(join(tmpdir(), "veraud-guard-"))

    assert.throws(
      () => sanitizeDirectInput({ root_path: `${workspace}-evil` }, workspace),
      InvalidDirectInputError,
    )
  })

  it("fails the checkout check when the folder is missing or empty", () => {
    const workspace = mkdtempSync(join(tmpdir(), "veraud-guard-"))

    assert.throws(() => assertDirectCheckout({ root_path: join(workspace, "missing") }), WorkspaceMissingError)

    const empty = join(workspace, "empty")
    mkdirSync(empty, { recursive: true })
    assert.throws(() => assertDirectCheckout({ root_path: empty }), WorkspaceMissingError)
  })

  it("accepts a checkout with content", () => {
    const workspace = mkdtempSync(join(tmpdir(), "veraud-guard-"))
    const checkout = join(workspace, "proj")
    mkdirSync(checkout, { recursive: true })
    writeFileSync(join(checkout, "README.md"), "# ok\n")

    assert.doesNotThrow(() => assertDirectCheckout({ root_path: checkout }))
  })
})

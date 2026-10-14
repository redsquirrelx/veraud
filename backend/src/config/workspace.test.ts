import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { defaultWorkspaceDir, findRepoRoot, resolveWorkspaceDir } from "./workspace.js"

describe("workspace resolution", () => {
  it("finds the repo root by git marker from any nested package", () => {
    const root = mkdtempSync(join(tmpdir(), "veraud-ws-"))
    mkdirSync(join(root, ".git"), { recursive: true })
    mkdirSync(join(root, "backend", "src", "config"), { recursive: true })

    assert.equal(findRepoRoot(join(root, "backend", "src", "config")), root)
    assert.equal(defaultWorkspaceDir(join(root, "backend")), join(root, "appdata", "workspace"))
  })

  it("falls back to the historical layout without a git marker", () => {
    const root = mkdtempSync(join(tmpdir(), "veraud-ws-"))
    mkdirSync(join(root, "backend"), { recursive: true })

    assert.equal(findRepoRoot(join(root, "backend")), null)
    assert.equal(defaultWorkspaceDir(join(root, "backend")), join(root, "appdata", "workspace"))
  })

  it("prefers the explicit override", () => {
    assert.equal(resolveWorkspaceDir("/repo/backend", "C:/data/checkouts"), "C:/data/checkouts")
    assert.equal(resolveWorkspaceDir("/repo/backend", ""), join(resolve("/repo/backend", ".."), "appdata", "workspace"))
  })
})

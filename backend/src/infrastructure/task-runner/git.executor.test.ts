import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { describeGitCommand, gitArgv, touchesProjectStatus } from "./git.executor.js"

describe("git executor", () => {
  it("builds argv without shell interpolation", () => {
    assert.deepEqual(gitArgv({ kind: "clone", cloneUrl: "https://example.com/repo.git", folder: "folder" }, "/ws/folder"), [
      "clone",
      "https://example.com/repo.git",
      "/ws/folder",
    ])
    assert.deepEqual(gitArgv({ kind: "pull", folder: "folder" }, "/ws/folder"), ["-C", "/ws/folder", "pull"])
    assert.deepEqual(gitArgv({ kind: "fetch", folder: "folder" }, "/ws/folder"), ["-C", "/ws/folder", "fetch"])
    assert.deepEqual(gitArgv({ kind: "list-branches", folder: "folder" }, "/ws/folder"), ["-C", "/ws/folder", "branch", "-a"])
    assert.deepEqual(gitArgv({ kind: "rev-parse", folder: "folder", branch: "main" }, "/ws/folder"), [
      "-C",
      "/ws/folder",
      "rev-parse",
      "main",
    ])
    assert.deepEqual(gitArgv({ kind: "checkout-detach", folder: "folder", commitHash: "abc1234" }, "/ws/folder"), [
      "-C",
      "/ws/folder",
      "checkout",
      "--force",
      "--detach",
      "abc1234",
    ])
    assert.deepEqual(gitArgv({ kind: "checkout-branch", folder: "folder", branch: "feature" }, "/ws/folder"), [
      "-C",
      "/ws/folder",
      "checkout",
      "--force",
      "feature",
    ])
    assert.deepEqual(gitArgv({ kind: "log-commits", folder: "folder", branch: "main", limit: 30, offset: 5 }, "/ws/folder"), [
      "-C",
      "/ws/folder",
      "log",
      "--format=%H%x09%s",
      "--max-count=30",
      "--skip=5",
      "main",
    ])
  })

  it("marks only clone and pull as mutating", () => {    assert.equal(touchesProjectStatus({ kind: "clone", cloneUrl: "url", folder: "folder" }), true)
    assert.equal(touchesProjectStatus({ kind: "pull", folder: "folder" }), true)
    assert.equal(touchesProjectStatus({ kind: "fetch", folder: "folder" }), true)
    assert.equal(touchesProjectStatus({ kind: "list-branches", folder: "folder" }), false)
    assert.equal(touchesProjectStatus({ kind: "rev-parse", folder: "folder", branch: "main" }), false)
    assert.equal(touchesProjectStatus({ kind: "checkout-detach", folder: "folder", commitHash: "abc1234" }), false)
    assert.equal(touchesProjectStatus({ kind: "checkout-branch", folder: "folder", branch: "feature" }), false)
    assert.equal(touchesProjectStatus({ kind: "log-commits", folder: "folder", branch: "main", limit: 30, offset: 0 }), false)
  })

  it("describes the execution resolving the workspace folder", () => {
    const described = describeGitCommand({ kind: "rev-parse", folder: "folder", branch: "main" }, "/ws")

    assert.equal(described.binary, "git")
    assert.equal(described.mutating, false)
    assert.ok(described.argv.includes("rev-parse"))
    assert.ok(described.argv.includes("main"))
  })
})

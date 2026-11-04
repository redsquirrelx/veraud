import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { existsSync, mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { setTimeout as delay } from "node:timers/promises"
import { describeGitCommand, executeGit, formatCommand, gitArgv, gitEnvironment, gitExecutionOptions, REMOTE_GIT_TIMEOUT_MS, touchesProjectStatus } from "./git.executor.js"

describe("git executor", () => {
  it("makes remote Git operations non-interactive and retains the external SSH environment", () => {
    const env = gitEnvironment(true, {
      PATH: "external-path",
      SSH_AUTH_SOCK: "external-agent-socket",
      GIT_SSH_COMMAND: "ssh -i /home/user/.ssh/work-key",
      HOME: "/home/user",
    })

    assert.equal(env.GIT_TERMINAL_PROMPT, "0")
    assert.equal(env.GCM_INTERACTIVE, "Never")
    assert.equal(env.SSH_AUTH_SOCK, "external-agent-socket")
    assert.equal(env.HOME, "/home/user")
    assert.match(env.GIT_SSH_COMMAND ?? "", /^ssh -i \/home\/user\/\.ssh\/work-key /)
    for (const option of ["BatchMode=yes", "NumberOfPasswordPrompts=0", "ConnectTimeout=15", "ConnectionAttempts=1", "StrictHostKeyChecking=yes"]) {
      assert.ok(env.GIT_SSH_COMMAND?.includes(`-o ${option}`), `missing ${option}`)
    }
    assert.equal(gitEnvironment(false, env), env)
    assert.deepEqual(gitExecutionOptions({ kind: "clone", cloneUrl: "git@github.com:acme/repo.git", folder: "repo" }), {
      remote: true, timeoutMs: REMOTE_GIT_TIMEOUT_MS,
    })
    assert.deepEqual(gitExecutionOptions({ kind: "list-branches", folder: "repo" }), { remote: false })
  })

  it("reports captured SSH authentication errors instead of waiting for terminal input", async () => {
    await assert.rejects(
      executeGit(process.execPath, ["-e", 'process.stderr.write("Permission denied (publickey)\\n"); process.exit(1)'], { remote: true, timeoutMs: 5000 }),
      /Permission denied \(publickey\)/,
    )
  })

  it("times out remote commands and terminates their child process tree", async () => {
    const directory = mkdtempSync(join(tmpdir(), "veraud-git-timeout-"))
    const marker = join(directory, "survived")
    const childScript = `setTimeout(() => require("node:fs").writeFileSync(${JSON.stringify(marker)}, "survived"), 1400)`
    const parentScript = `require("node:child_process").spawn(process.execPath, ["-e", ${JSON.stringify(childScript)}], { stdio: "ignore" }); setInterval(() => {}, 1000)`
    try {
      await assert.rejects(executeGit(process.execPath, ["-e", parentScript], { remote: true, timeoutMs: 350 }), /timed out after 350ms/i)
      await delay(1550)
      assert.equal(existsSync(marker), false, "the spawned descendant should be terminated with Git")
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  })

  it("formats arguments with spaces, quotes and empty values unambiguously", () => {
    assert.equal(formatCommand("git", ["clone", "--depth", "1", "git@github.com:acme/repo.git", "/workspace/my repo"]), 'git clone --depth 1 git@github.com:acme/repo.git "/workspace/my repo"')
    assert.equal(formatCommand("git", ["", 'a"b']), 'git "" "a\\"b"')
  })
  it("uses depth 1 only for shallow clones over HTTPS and SSH", () => {
    for (const cloneUrl of ["https://github.com/acme/repo.git", "git@github.com:acme/repo.git"]) {
      assert.deepEqual(gitArgv({ kind: "clone", cloneUrl, folder: "folder", shallowClone: true }, "/ws/folder"), ["clone", "--depth", "1", cloneUrl, "/ws/folder"])
      assert.deepEqual(gitArgv({ kind: "clone", cloneUrl, folder: "folder", shallowClone: false }, "/ws/folder"), ["clone", cloneUrl, "/ws/folder"])
    }
  })
  it("builds argv without shell interpolation", () => {
    assert.deepEqual(gitArgv({ kind: "clone", cloneUrl: "https://example.com/repo.git", folder: "folder" }, "/ws/folder"), [
      "clone",
      "https://example.com/repo.git",
      "/ws/folder",
    ])
    assert.deepEqual(gitArgv({ kind: "pull", folder: "folder" }, "/ws/folder"), ["-C", "/ws/folder", "pull"])
    assert.deepEqual(gitArgv({ kind: "fetch", folder: "folder" }, "/ws/folder"), ["-C", "/ws/folder", "fetch"])
    assert.deepEqual(gitArgv({ kind: "list-branches", folder: "folder" }, "/ws/folder"), ["-C", "/ws/folder", "branch", "-a"])
    assert.deepEqual(gitArgv({ kind: "list-tree", folder: "folder" }, "/ws/folder"), [
      "-C",
      "/ws/folder",
      "ls-tree",
      "-r",
      "--name-only",
      "HEAD",
    ])
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
    assert.equal(touchesProjectStatus({ kind: "list-tree", folder: "folder" }), false)
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

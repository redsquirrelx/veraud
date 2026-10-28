import { it } from "node:test"
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { ProjectService, ProjectFileError, InvalidGitRequestError } from "./project.service.js"
import type { ProjectStore, StoredProjectDetails } from "./project.repository.js"
import type { TaskService } from "../task/task.service.js"
import type { GithubClient } from "../../infrastructure/github-client/github.client.js"

function fixture() {
  const base = process.platform === "win32" ? join(tmpdir(), "opencode") : tmpdir()
  mkdirSync(base, { recursive: true })
  const root = mkdtempSync(join(base, "audit-history-"))
  const cwd = join(root, "1-acme-Demo")
  mkdirSync(cwd)
  const git = (...args: string[]) => execFileSync("git", args, { cwd, encoding: "utf8", windowsHide: true }).trim()
  git("init", "-q")
  git("config", "user.name", "Synthetic test")
  git("config", "user.email", "test@example.invalid")
  git("config", "core.autocrlf", "false")
  writeFileSync(join(cwd, "source.ts"), "// audited\nexport const value = 1\n")
  writeFileSync(join(cwd, "empty.ts"), "")
  writeFileSync(join(cwd, "binary.bin"), Buffer.from([1, 0, 2]))
  writeFileSync(join(cwd, "large.ts"), "a".repeat(512 * 1024 + 1))
  mkdirSync(join(cwd, "directory"))
  writeFileSync(join(cwd, "directory", "nested.ts"), "nested")
  git("add", ".")
  const blob = git("hash-object", "-w", "source.ts")
  git("update-index", "--add", "--cacheinfo", `120000,${blob},link.ts`)
  git("commit", "-qm", "audited revision")
  const commit = git("rev-parse", "HEAD")
  writeFileSync(join(cwd, "source.ts"), "// later version\nexport const value = 2\n")
  git("add", "source.ts")
  git("commit", "-qm", "later revision")
  writeFileSync(join(cwd, "source.ts"), "// uncommitted current content")
  const project = { id: 2, githubRepositoryId: 1n, repositoryOwner: "acme", repositoryName: "Demo" } as StoredProjectDetails
  const service = new ProjectService({ findById: async () => project } as unknown as ProjectStore,
    {} as TaskService, {} as GithubClient, root, { openProjectArchitecturePipelineForProject: async () => { throw new Error("must not run analyses") } })
  return { service, commit, git, close: () => rmSync(root, { recursive: true, force: true }) }
}

it("reads the audited Git blob rather than later or dirty checkout content, without changing HEAD or status", async () => {
  const f = fixture()
  try {
    const head = f.git("rev-parse", "HEAD")
    const status = f.git("status", "--porcelain")
    const file = await f.service.readFileAtCommit(2, "source.ts", f.commit)
    assert.equal(file.content, "// audited\nexport const value = 1\n")
    assert.equal(file.commitHash, f.commit)
    assert.equal(file.size, Buffer.byteLength(file.content))
    assert.equal(f.git("rev-parse", "HEAD"), head)
    assert.equal(f.git("status", "--porcelain"), status)
    assert.equal((await f.service.readFileAtCommit(2, "empty.ts", f.commit)).content, "")
  } finally { f.close() }
})

it("rejects missing history, absent paths, directories, symlinks, binary and oversized blobs without falling back", async () => {
  const f = fixture()
  try {
    for (const path of ["missing.ts", "directory", "link.ts", "binary.bin", "large.ts", "*.ts"]) {
      await assert.rejects(f.service.readFileAtCommit(2, path, f.commit), ProjectFileError)
    }
    await assert.rejects(f.service.readFileAtCommit(2, "source.ts", "f".repeat(40)), ProjectFileError)
    for (const path of ["../source.ts", "/source.ts", "C:\\source.ts", ".git/config", "a/.git/config"]) {
      await assert.rejects(f.service.readFileAtCommit(2, path, f.commit), InvalidGitRequestError)
    }
    await assert.rejects(f.service.readFileAtCommit(2, "source.ts", "HEAD"), ProjectFileError)
  } finally { f.close() }
})

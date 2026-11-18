import { execFileSync } from "node:child_process"
import { mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"

/** Deterministic synthetic repository used by every black-box test that
 *  exercises git read-paths (tree, file, branches, log). Consumers get the
 *  commit hashes via the seed state rather than guessing them. */

export const OWNER = "e2e-owner"
export const REPOSITORY = "e2e-sandbox"
export const GITHUB_REPOSITORY_ID = "9900000001"
export const FEATURE_BRANCH = "feature/sample"

const SOURCE = `// Synthetic source committed by the E2E harness.
export function releaseNotes(): string {
  return "Veraud sandbox: the answer is always 42"
}

export function criticalBugs(): number {
  return 0
}
`

function git(cwd, args, date) {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_AUTHOR_DATE: date,
      GIT_COMMITTER_DATE: date,
      GIT_AUTHOR_NAME: "Veraud E2E",
      GIT_AUTHOR_EMAIL: "e2e@example.com",
      GIT_COMMITTER_NAME: "Veraud E2E",
      GIT_COMMITTER_EMAIL: "e2e@example.com",
    },
  }).trim()
}

/** Creates a fresh checkout with an "main" branch (one commit) and a second
 *  commit on a feature branch, then returns to "main". */
export function buildSyntheticRepo(root) {
  const folder = `${GITHUB_REPOSITORY_ID}-${OWNER}-${REPOSITORY}`
  const workspaceRepoDir = join(root, folder)
  mkdirSync(join(workspaceRepoDir, "src"), { recursive: true })

  writeFileSync(join(workspaceRepoDir, "package.json"), JSON.stringify({
    name: "e2e-sandbox",
    version: "1.0.0",
    private: true,
    type: "module",
  }, null, 2) + "\n")
  writeFileSync(join(workspaceRepoDir, "README.md"), "# Veraud E2E sandbox\n\nSynthetic repository used by black-box tests.\n")
  writeFileSync(join(workspaceRepoDir, "src", "index.ts"), SOURCE)

  git(workspaceRepoDir, ["init", "-b", "main"], "2026-11-10T10:00:00Z")
  git(workspaceRepoDir, ["add", "."], "2026-11-10T10:00:00Z")
  git(workspaceRepoDir, ["commit", "-m", "Synthetic sandbox: initial import"], "2026-11-10T10:00:00Z")
  const mainCommit = git(workspaceRepoDir, ["rev-parse", "HEAD"], "2026-11-10T10:00:00Z")

  git(workspaceRepoDir, ["switch", "-c", FEATURE_BRANCH], "2026-11-12T10:00:00Z")
  writeFileSync(join(workspaceRepoDir, "src", "feature.ts"), "export const featureFlag = true\n")
  git(workspaceRepoDir, ["add", "."], "2026-11-12T10:00:00Z")
  git(workspaceRepoDir, ["commit", "-m", "Synthetic sandbox: feature branch"], "2026-11-12T10:00:00Z")
  const featureCommit = git(workspaceRepoDir, ["rev-parse", "HEAD"], "2026-11-12T10:00:00Z")
  git(workspaceRepoDir, ["switch", "main"], "2026-11-10T10:00:00Z")

  return { workspaceRepoDir, featureBranch: FEATURE_BRANCH, mainCommit, featureCommit }
}

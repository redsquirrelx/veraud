import { execFileSync } from "node:child_process"
import { mkdirSync, rmSync, writeFileSync } from "node:fs"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const e2eDir = resolve(here, "..")
const repoRoot = resolve(here, "..", "..")
const appdata = join(e2eDir, ".appdata")
const workspace = join(appdata, "workspace")
const databaseUrl = "file:" + join(appdata, "database.db").replaceAll("\\", "/")

/** Rebuilds the isolated E2E appdata from scratch: synthetic git repo,
 *  freshly migrated SQLite schema and the seed rows the suite relies on.
 *  Deliberately synchronous and chatty — failures must be loud.
 */
mkdirSync(appdata, { recursive: true })
rmSync(appdata, { recursive: true, force: true })
mkdirSync(workspace, { recursive: true })
mkdirSync(join(appdata, "graphs"), { recursive: true })
console.error("[prepare] workspace ready:", workspace)

const repo = await import(pathToFileURL(join(here, "git-repo.mjs")).href).then((mod) => mod.buildSyntheticRepo(workspace))
console.error("[prepare] synthetic repo at", repo.workspaceRepoDir, repo.mainCommit.slice(0, 7))

const backendDir = join(repoRoot, "backend")
try {
  execFileSync("pnpm", ["exec", "prisma", "migrate", "deploy"], { cwd: backendDir, stdio: "inherit", env: { ...process.env, DATABASE_URL: databaseUrl } })
  console.error("[prepare] schema migrated")
} catch (error) {
  console.error("[prepare] prisma migrate deploy failed")
  throw error
}

// tsx compiles the generated Prisma TypeScript client on the fly (exactly as the backend dev server does).
execFileSync("pnpm", ["exec", "tsx", join(here, "seed.mjs")], {
  cwd: backendDir,
  stdio: "inherit",
  env: { ...process.env, DATABASE_URL: databaseUrl, SEED_MAIN_COMMIT: repo.mainCommit, SEED_FEATURE_COMMIT: repo.featureCommit, SEED_STATE_PATH: join(appdata, "seed-state.json") },
})
console.error("[prepare] seed complete")
writeFileSync(join(appdata, "database.db-ready"), new Date().toISOString())

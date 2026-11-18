import { execFileSync } from "node:child_process"
import { cpSync, mkdirSync, rmSync, writeFileSync, existsSync, readdirSync } from "node:fs"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { createRequire } from "node:module"
const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, "..", "..")

// better-sqlite3 is a backend dependency; resolve it from the backend's pnpm store.
const pnpmStore = join(repoRoot, "backend", "node_modules", ".pnpm")
const betterSqliteDir = readdirSync(pnpmStore).find((entry) => entry.startsWith("better-sqlite3@"))
if (!betterSqliteDir) throw new Error(`better-sqlite3 not found in ${pnpmStore}`)
const requireBackend = createRequire(pathToFileURL(join(pnpmStore, betterSqliteDir, "node_modules", "better-sqlite3", "package.json")).href)
const Database = requireBackend("better-sqlite3")
const appdata = process.env.VERAUD_E2E_LIVE_APPDATA ?? join(repoRoot, "e2e", ".live-appdata")
const devAppdata = join(repoRoot, "appdata")
const backendDir = join(repoRoot, "backend")
const devDatabase = join(devAppdata, "database.db")
const liveWorkspace = join(appdata, "workspace")
const devWorkspace = join(devAppdata, "workspace")
const devSecrets = join(devWorkspace, ".secrets")
const liveSecrets = join(liveWorkspace, ".secrets")
const devCheckout = join(devWorkspace, "1373928788-Cesar-Sanchez-sof-Polleria")
const liveCheckout = join(liveWorkspace, "1373928788-Cesar-Sanchez-sof-Polleria")
const expectedCommit = "b516646312b44b24c42b608fa9d379922b34ee08"
const statePath = join(appdata, "live-seed-state.json")

/** Recreates the LIVE sandbox from the developer appdata, read-only. The
 *  developer appdata is never mutated; the live one is gitignored scratch
 *  that contains a copy of the DPAPI master key and copies of the encrypted
 *  provider credentials. Delete freely: `pnpm --dir e2e live:bootstrap` rebuilds it. */
console.error("[live] recreating", appdata)
rmSync(appdata, { recursive: true, force: true })
mkdirSync(liveWorkspace, { recursive: true })
mkdirSync(join(appdata, "graphs"), { recursive: true })
mkdirSync(liveSecrets, { recursive: true })

if (!existsSync(devDatabase)) throw new Error(`dev database not found at ${devDatabase}`)
if (!existsSync(devCheckout)) throw new Error(`polleria checkout not found at ${devCheckout}`)
if (!existsSync(join(devSecrets, "credential-master.v1.dpapi"))) throw new Error("credential-master.v1.dpapi not found; live runs would fail credential decryption")

console.error("[live] copying polleria checkout")
cpSync(devCheckout, liveCheckout, { recursive: true })
const head = execFileSync("git", ["rev-parse", "HEAD"], { cwd: liveCheckout, encoding: "utf8" }).trim()
if (head !== expectedCommit) throw new Error(`polleria HEAD ${head} != ${expectedCommit}; refuse to run live against an unexpected revision`)
console.error("[live] HEAD verified:", head.slice(0, 7))

console.error("[live] copying DPAPI master key")
cpSync(join(devSecrets, "credential-master.v1.dpapi"), join(liveSecrets, "credential-master.v1.dpapi"))

console.error("[live] migrating live database schema")
const liveDatabaseUrl = "file:" + join(appdata, "database.db").replaceAll("\\", "/")
execFileSync("pnpm", ["exec", "prisma", "migrate", "deploy"], { cwd: backendDir, stdio: "inherit", env: { ...process.env, DATABASE_URL: liveDatabaseUrl } })

console.error("[live] copying dev DB rows (read-only source)")
const src = new Database(devDatabase, { readonly: true })
const dst = new Database(join(appdata, "database.db"))
const copy = (table, where) => {
  const rows = src.prepare(`select * from ${table}${where ? ` where ${where}` : ""}`).all()
  if (rows.length === 0) return 0
  const cols = Object.keys(rows[0])
  const stmt = dst.prepare(`insert into ${table} (${cols.map((c) => `"${c}"`).join(",")}) values (${cols.map(() => "?").join(",")})`)
  for (const row of rows) {
    try { stmt.run(...cols.map((c) => row[c])) } catch (error) {
      console.error(`[live] FAILED copying ${table} row`, JSON.stringify(row, (k, v) => (typeof v === "bigint" ? v.toString() : v)))
      throw error
    }
  }
  return rows.length
}
const tx = dst.transaction(() => {
  const counts = {
    ai_provider: copy("ai_provider"),
    ai_model: copy("ai_model"),
    ai_credential: copy("ai_credential"),
    agent_settings: copy("agent_settings"),
    agent_hierarchy: copy("agent_hierarchy"),
    audit_settings: copy("audit_settings"),
  }
  // Project and version reference each other: version first would need the
  // project, project first would need the version. Insert project with a
  // null selected_version_id, then the version, then wire them up.
  const projectRow = src.prepare("select * from project where id = 2").get()
  dst.prepare(`insert into project (${Object.keys(projectRow).map((c) => `"${c}"`).join(",")}) values (${Object.keys(projectRow).map(() => "?").join(",")})`)
    .run(...Object.values({ ...projectRow, selected_version_id: null }))
  counts.project = 1
  counts.project_version = copy("project_version", "id = 20")
  dst.prepare("update project set selected_version_id = 20 where id = 2").run()
  dst.prepare("update project_version set analysis_status='Pending', analyzed_at=null where id=20").run()
  return counts
})
const counts = tx()
console.error("[live] copied:", JSON.stringify(counts))
dst.close()
src.close()
writeFileSync(statePath, JSON.stringify({ projectId: 2, versionId: 20, commit: head }, null, 2))
console.error("[live] bootstrap complete")

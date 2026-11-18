import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, "..", "..")
const appdata = join(repoRoot, "e2e", process.argv[2] ?? ".live-appdata")
const snapshot = join(repoRoot, "e2e", ".live-appdata-snapshot")
if (!existsSync(snapshot)) throw new Error(`snapshot missing: ${snapshot}`)
rmSync(appdata, { recursive: true, force: true })
mkdirSync(appdata, { recursive: true })
cpSync(snapshot, appdata, { recursive: true })
console.error("[live] restored", snapshot, "into", appdata)

import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, "..", "..")
const appdata = join(repoRoot, "e2e", ".live-appdata")
const snapshot = join(repoRoot, "e2e", ".live-appdata-snapshot")
if (!existsSync(appdata)) throw new Error(`live sandbox missing: ${appdata}`)
rmSync(snapshot, { recursive: true, force: true })
mkdirSync(snapshot, { recursive: true })
cpSync(appdata, snapshot, { recursive: true })
console.error("[live] snapshot saved to", snapshot)

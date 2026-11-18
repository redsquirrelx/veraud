import { readFileSync } from "node:fs"
import { join, dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))

export interface LiveState {
  projectId: number
  versionId: number
  commit: string
}

export const live: LiveState = JSON.parse(readFileSync(join(resolve(here, "..", ".."), ".live-appdata", "live-seed-state.json"), "utf8")) as LiveState

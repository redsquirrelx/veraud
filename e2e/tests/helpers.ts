import { readFileSync } from "node:fs"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import type { Page } from "@playwright/test"

const here = dirname(fileURLToPath(import.meta.url))

export interface SeedState {
  projectId: number
  mainVersionId: number
  featureVersionId: number
  mainCommit: string
  featureCommit: string
  evaluations: Record<string, number>
  executions: Record<string, number>
}

export const seed: SeedState = JSON.parse(readFileSync(join(here, "..", ".appdata", "seed-state.json"), "utf8")) as SeedState

/** Switches the UI to Spanish for this browser context. Must be called before navigation. */
export async function useSpanish(page: Page) {
  await page.addInitScript(() => { window.localStorage.setItem("settings.language", JSON.stringify("es")) })
}

/** Opens the Execution Explorer from the nav rail/dock. */
export async function openExplorer(page: Page, executionsLabelPattern: RegExp | string) {
  await page.getByRole("button", { name: executionsLabelPattern }).click()
}

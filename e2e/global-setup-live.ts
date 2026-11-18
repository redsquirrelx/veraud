import { execFileSync } from "node:child_process"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))

export default async function globalSetup() {
  if (process.env.VERAUD_E2E_LIVE_FROM_SNAPSHOT !== "1") {
    execFileSync("node", [join(here, "helpers", "prepare-live.mjs")], { cwd: resolve(here, ".."), stdio: "inherit" })
  } else {
    execFileSync("node", [join(here, "helpers", "restore-live.mjs")], { cwd: resolve(here, ".."), stdio: "inherit" })
  }
  const { startLiveStack } = await import("./helpers/stack-live.mjs")
  return await startLiveStack()
}

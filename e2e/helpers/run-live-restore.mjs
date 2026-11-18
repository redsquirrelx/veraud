import { spawnSync } from "node:child_process"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))

process.env.VERAUD_E2E_LIVE_FROM_SNAPSHOT = "1"
const result = spawnSync(
  process.execPath,
  [join(here, "..", "node_modules", ".bin", "playwright"), "test", "--config", "playwright.config.live.ts", ...process.argv.slice(2)],
  { cwd: join(here, ".."), stdio: "inherit", shell: true },
)
process.exit(result.status ?? 1)

import { execFileSync } from "node:child_process"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, "..")

/** Rebuilds the isolated appdata, then boots backend / agent-server / frontend
 *  on fresh ports (7601/7602/7600). Called once per playwright invocation and
 *  the returned teardown kills every spawned process tree. */
export default async function globalSetup() {
  execFileSync("node", [join(here, "helpers", "prepare.mjs")], { cwd: repoRoot, stdio: "inherit" })

  // Imported lazily so the stack only boots after the appdata exists.
  const { startStack } = await import("./helpers/stack.mjs")
  const teardown = await startStack()
  return teardown
}

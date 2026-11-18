import { execFileSync, spawn } from "node:child_process"
import { createWriteStream, mkdirSync } from "node:fs"
import { join, resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const e2eDir = resolve(here, "..")
const repoRoot = resolve(here, "..", "..")

export const stack = {
  frontendPort: 7600,
  backendPort: 7601,
  agentServerPort: 7602,
  appdata: process.env.VERAUD_E2E_LIVE_APPDATA ?? join(e2eDir, ".live-appdata"),
  databaseUrl: process.env.VERAUD_E2E_LIVE_APPDATA
    ? "file:" + join(process.env.VERAUD_E2E_LIVE_APPDATA, "database.db").replaceAll("\\", "/")
    : "file:" + join(e2eDir, ".live-appdata", "database.db").replaceAll("\\", "/"),
}

function launch(name, commandLine, cwd, env) {
  mkdirSync(stack.appdata, { recursive: true })
  const out = createWriteStream(join(stack.appdata, `${name}.log`), { flags: "a" })
  const child = spawn(commandLine, { cwd, env: { ...process.env, ...env }, shell: true, detached: true, stdio: ["ignore", "pipe", "pipe"], windowsHide: true })
  child.stdout?.pipe(out)
  child.stderr?.pipe(out)
  return {
    pid: child.pid ?? 0,
    kill: () => execFileSync("taskkill", ["/T", "/F", "/PID", String(child.pid)], { stdio: "ignore" }),
  }
}

export async function waitForUrl(url, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2_000) })
      if (res.ok) return
    } catch { /* not up yet */ }
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${url} (see ${stack.appdata} logs)`)
    await new Promise((wait) => setTimeout(wait, 2_000))
  }
}

export async function startLiveStack() {
  const common = {
    PORT_BACKEND: String(stack.backendPort),
    PORT_AGENTSERVER: String(stack.agentServerPort),
    HOST: `http://127.0.0.1:${stack.frontendPort}/`,
    DATABASE_URL: stack.databaseUrl,
    WORKSPACE_DIR: join(stack.appdata, "workspace"),
    WORKSPACE_ROOT: join(stack.appdata, "workspace"),
    LLM_API_KEY: "e2e-live-unused",
  }
  const backend = launch("backend", "pnpm exec tsx ./src/index.ts", join(repoRoot, "backend"), common)
  const agentServer = launch("agent-server", "uv run dev", join(repoRoot, "agent-server"), common)
  const frontend = launch("frontend", `pnpm exec vite --port ${stack.frontendPort} --strictPort --host 127.0.0.1`, join(repoRoot, "frontend"), { VITE_BACKEND_URL: `http://127.0.0.1:${stack.backendPort}` })

  const teardown = () => {
    for (const child of [frontend, agentServer, backend]) {
      try { child.kill() } catch { /* already gone */ }
    }
  }
  try {
    await waitForUrl(`http://127.0.0.1:${stack.backendPort}/api/projects`, 120_000)
    console.error("[live-stack] backend ready")
    await waitForUrl(`http://127.0.0.1:${stack.agentServerPort}/openapi.json`, 180_000)
    console.error("[live-stack] agent-server ready")
    await waitForUrl(`http://127.0.0.1:${stack.frontendPort}/`, 60_000)
    console.error("[live-stack] frontend ready")
  } catch (error) {
    teardown()
    throw error
  }
  return teardown
}

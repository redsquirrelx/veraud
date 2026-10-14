import { fileURLToPath } from "node:url"
import { logger } from "./config/logger.js"
import { buildApp } from "./app.js"

import { env } from "./config/env.js"
import { resolveWorkspaceDir } from "./config/workspace.js"

const projectRoot = fileURLToPath(new URL("../../", import.meta.url))

// Checkouts live in the repo appdata/workspace shared with the agent-server
// (next to DATABASE_URL), unless WORKSPACE_DIR overrides it. The root is
// located by git marker so every package resolves the same directory.
const workspaceDir = resolveWorkspaceDir(projectRoot, env.WORKSPACE_DIR)

const { app } = await buildApp({
  databaseUrl: env.DATABASE_URL,
  workspaceDir,
  agentServerUrl: `http://localhost:${env.PORT_AGENTSERVER}`,
})

logger.withTag("workspace").info(
  `Checkout root: ${workspaceDir} (WORKSPACE_DIR ${env.WORKSPACE_DIR !== "" ? "override" : "unset"})`,
)

app.addHook('onReady', async () => {
  const log = logger.withTag('agent-server')
  const port = env.PORT_AGENTSERVER
  const base = `http://localhost:${port}`

  try {
    // The agent-server serves this under /api, like its run endpoint.
    const response = await fetch(`${base}/api/status`)

    if (!response.ok) {
      throw new Error(`Agent server returned ${response.status}`)
    }

    log.info(`Agent server at ${port} is available`)
  } catch (error) {
    log.error(`Agent server at ${port} is unavailable. Details: ${error}`)
  }
})

app.listen({ port: env.PORT_BACKEND }, (error, address) => {
  if (error !== null) {
    console.error(`Backend failed to start: ${error.message}`)
    process.exit(1)
  }
  console.log(`Backend listening at ${address}`)
})
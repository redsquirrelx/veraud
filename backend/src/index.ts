import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { logger } from "./config/logger.js"
import { buildApp } from "./app.js"

import { env } from "./config/env.js"

const projectRoot = fileURLToPath(new URL("../../", import.meta.url))

const { app } = await buildApp({
  databaseUrl: env.DATABASE_URL,
  workspaceDir: join(projectRoot, "appdata", "workspace"),
  agentServerUrl: `http://localhost:${env.PORT_AGENTSERVER}`,
})

app.addHook('onReady', async () => {
  const log = logger.withTag('agent-server')
  const port = env.PORT_AGENTSERVER

  try {
    const response = await fetch(`http://localhost:${port}/status`)

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
import Fastify from "fastify";
import { logger } from "./config/logger.js"

import { PrismaClient } from "./generated/prisma/client.js"
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3"

const adapter = new PrismaBetterSqlite3({
  url: process.env.DATABASE_URL 
})

const dbClient = new PrismaClient({ adapter })

const app = Fastify({
  logger: {
    transport: {
      target: "pino-pretty",
      options: {
        colorize: true,
        translateTime: 'HH:MM:ss',
        ignore: 'pid,hostname',
      },
    }
  }
});

logger.configure(app.log)

const log = logger.withTag('bd-test')
dbClient.project.create({
  data: {
    name: "example",
    githubRepositoryId: 1251241412,
    repositoryName: "examplename",
    repositoryOwner: "ownerexample",
    status: "syncing"
  }
}).then(_ => {
  log.info("new project registered!")
})

app.addHook('onReady', async () => {
  const log = logger.withTag('agent-server')
  const port = process.env.PORT_AGENTSERVER ?? 3000

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

app.get("/status", async () => {
  const log = logger.withTag("status")
  log.info("Status requested")

  return {
    status: "ok",
    service: "backend"
  }
})

app.listen({
  port: Number(process.env.PORT_BACKEND ?? 3000)
});
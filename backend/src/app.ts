import { mkdirSync } from "node:fs"
import Fastify from "fastify"
import cors from "@fastify/cors"
import websocket from "@fastify/websocket"
import pretty from "pino-pretty"
import { logger } from "./config/logger.js"

import { PrismaClient } from "./generated/prisma/client.js"
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3"

import { GithubClient } from "./infrastructure/github-client/github.client.js"
import { RealtimeGateway } from "./infrastructure/realtime-gateway/realtime.gateway.js"
import { TaskRunner, type TaskQueue } from "./infrastructure/task-runner/task.runner.js"
import { ProjectRepository } from "./modules/project/project.repository.js"
import { ProjectService } from "./modules/project/project.service.js"
import { registerProjectRoutes } from "./modules/project/project.controller.js"
import { AgentExecutionRepository } from "./modules/agent-execution/agent-execution.repository.js"
import { AgentExecutionService } from "./modules/agent-execution/agent-execution.service.js"
import { registerAgentExecutionRoutes } from "./modules/agent-execution/agent-execution.controller.js"
import { AiProviderRepository } from "./modules/ai-provider/ai-provider.repository.js"
import { AiProviderService, SEEDED_AI_PROVIDERS } from "./modules/ai-provider/ai-provider.service.js"
import { registerAiProviderRoutes } from "./modules/ai-provider/ai-provider.controller.js"
import { TaskRepository } from "./modules/task/task.repository.js"
import { TaskService } from "./modules/task/task.service.js"
import { registerTaskRoutes } from "./modules/task/task.controller.js"

export interface BuildAppOptions {
  databaseUrl: string
  workspaceDir: string
  silent?: boolean
  agentServerUrl?: string
  makeRunner?: (tasks: TaskRepository, projects: ProjectRepository, gateway: RealtimeGateway) => TaskQueue
}

export async function buildApp(options: BuildAppOptions) {
  const stream = pretty({ colorize: true, translateTime: "HH:MM:ss", ignore: "pid,hostname" })
  const app = Fastify({ logger: options.silent === true ? false : { level: "info", stream } })
  logger.configure(app.log)

  const db = new PrismaClient({
    adapter: new PrismaBetterSqlite3({ url: options.databaseUrl }),
  })

  mkdirSync(options.workspaceDir, { recursive: true })

  const gateway = new RealtimeGateway()
  const github = new GithubClient()
  const projectRepository = new ProjectRepository(db)
  const taskRepository = new TaskRepository(db)
  const runner = options.makeRunner
    ? options.makeRunner(taskRepository, projectRepository, gateway)
    : new TaskRunner(taskRepository, projectRepository, gateway, options.workspaceDir)
  const taskService = new TaskService(taskRepository, runner)
  const projectService = new ProjectService(projectRepository, taskService, github, options.workspaceDir)
  const aiProviderRepository = new AiProviderRepository(db)
  await aiProviderRepository.ensureSeeded(SEEDED_AI_PROVIDERS)
  const aiProviderService = new AiProviderService(aiProviderRepository)

  await app.register(websocket)
  await app.register(cors, {
    origin: [/^http:\/\/localhost:\d+$/, /^http:\/\/127\.0\.0\.1:\d+$/],
    methods: ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
  })
  
  gateway.register(app)
  registerProjectRoutes(app, projectService)
  registerAiProviderRoutes(app, aiProviderService)
  registerTaskRoutes(app, taskService)

  const agentExecutionRepository = new AgentExecutionRepository(db)
  const agentExecutionService = new AgentExecutionService(agentExecutionRepository)
  registerAgentExecutionRoutes(app, agentExecutionService, gateway)

  app.get("/status", { logLevel: "silent" }, async () => {
    return { status: "ok", service: "backend", agentServer: await checkAgentServer(options.agentServerUrl) }
  })

  return { app, db }
}

async function checkAgentServer(url: string | undefined): Promise<string> {
  if (url === undefined) {
    return "unknown"
  }
  try {
    const response = await fetch(`${url}/status`, { signal: AbortSignal.timeout(2000) })
    return response.ok ? "online" : "offline"
  } catch {
    return "offline"
  }
}

import { mkdirSync } from "node:fs"
import Fastify from "fastify"
import cors from "@fastify/cors"
import websocket from "@fastify/websocket"
import pretty from "pino-pretty"
import { logger } from "./config/logger.js"
import { registerOpenApi } from "./infrastructure/openapi/registerOpenApi.js"
import { registerApiSchemas } from "./infrastructure/openapi/registerApiSchemas.js"
import { registerAsyncApi } from "./infrastructure/asyncapi/registerAsyncApi.js"

import { PrismaClient } from "./generated/prisma/client.js"
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3"

import { GithubClient } from "./infrastructure/github-client/github.client.js"
import { RealtimeGateway } from "./infrastructure/realtime-gateway/realtime.gateway.js"
import { TaskRunner, type TaskQueue } from "./infrastructure/task-runner/task.runner.js"
import { AgentServerClient, type AgentInvoker } from "./infrastructure/agent-server-client/agent-server.client.js"
import {
  AgentTargetResolverImpl,
  type AgentTargetResolver,
} from "./infrastructure/agent-target/agent-target.resolver.js"
import { ProjectRepository } from "./modules/project/project.repository.js"
import { ProjectService } from "./modules/project/project.service.js"
import { registerProjectRoutes } from "./modules/project/project.controller.js"
import { QualityAuditRepository } from "./modules/quality-audit/quality-audit.repository.js"
import { QualityAuditService } from "./modules/quality-audit/quality-audit.service.js"
import { registerQualityAuditRoutes } from "./modules/quality-audit/quality-audit.controller.js"
import { AgentExecutionRepository } from "./modules/agent-execution/agent-execution.repository.js"
import { AgentExecutionService } from "./modules/agent-execution/agent-execution.service.js"
import { registerAgentExecutionRoutes } from "./modules/agent-execution/agent-execution.controller.js"
import { AiProviderRepository } from "./modules/ai-provider/ai-provider.repository.js"
import { AiProviderService, SEEDED_AI_PROVIDERS } from "./modules/ai-provider/ai-provider.service.js"
import { registerAiProviderRoutes } from "./modules/ai-provider/ai-provider.controller.js"
import { AgentSettingsRepository } from "./modules/agent-settings/agent-settings.repository.js"
import { AgentSettingsService } from "./modules/agent-settings/agent-settings.service.js"
import { registerAgentSettingsRoutes } from "./modules/agent-settings/agent-settings.controller.js"
import { BACKEND_AGENT_TYPES } from "./modules/agent-settings/agent-types.js"
import type { ModelAccessVerifier } from "./modules/agent-settings/agent-configuration.js"
import { TaskRepository } from "./modules/task/task.repository.js"
import { TaskService } from "./modules/task/task.service.js"
import { registerTaskRoutes } from "./modules/task/task.controller.js"

export interface BuildAppOptions {
  databaseUrl: string
  workspaceDir: string
  silent?: boolean
  agentServerUrl?: string
  makeRunner?: (tasks: TaskRepository, projects: ProjectRepository, gateway: RealtimeGateway) => TaskQueue
  /** How agents are reached and what they are invoked with. Tests override these
   *  to keep a run from leaving the machine; production leaves them unset. */
  makeAgentInvoker?: (agentServerUrl: string | undefined) => AgentInvoker
  makeAgentTargets?: (workspaceDir: string) => AgentTargetResolver
  makeModelAccessVerifier?: () => ModelAccessVerifier
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
  const agentSettingsRepository = new AgentSettingsRepository(db)
  await agentSettingsRepository.ensureSeeded(BACKEND_AGENT_TYPES)
  const verifier = options.makeModelAccessVerifier?.() ?? (options.agentServerUrl
    ? new AgentServerClient(options.agentServerUrl)
    : { verify: async () => { throw new Error("No agent-server URL configured; model access cannot be verified") } })
  const agentSettingsService = new AgentSettingsService(agentSettingsRepository, verifier)
  const agentExecutionRepository = new AgentExecutionRepository(db, agentSettingsRepository)
  const agentInvoker = options.makeAgentInvoker
    ? options.makeAgentInvoker(options.agentServerUrl)
    : buildAgentInvoker(options.agentServerUrl)
  const agentTargets = options.makeAgentTargets
    ? options.makeAgentTargets(options.workspaceDir)
    : new AgentTargetResolverImpl(db, options.workspaceDir)
  const agentExecutionService = new AgentExecutionService(
    agentExecutionRepository,
    agentInvoker,
    agentTargets,
    gateway,
    options.workspaceDir,
    agentSettingsService,
  )
  const projectService = new ProjectService(projectRepository, taskService, github, options.workspaceDir, agentExecutionService)
  const aiProviderRepository = new AiProviderRepository(db)
  await aiProviderRepository.ensureSeeded(SEEDED_AI_PROVIDERS)
  const aiProviderService = new AiProviderService(aiProviderRepository)

  await registerOpenApi(app)
  await registerAsyncApi(app)
  registerApiSchemas(app)
  await app.register(websocket)
  await app.register(cors, {
    origin: [/^http:\/\/localhost:\d+$/, /^http:\/\/127\.0\.0\.1:\d+$/],
    methods: ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
  })
  
  gateway.register(app)
  registerProjectRoutes(app, projectService)
  registerQualityAuditRoutes(app, new QualityAuditService(new QualityAuditRepository(db), projectService, agentExecutionService))
  registerAiProviderRoutes(app, aiProviderService)
  registerAgentSettingsRoutes(app, agentSettingsService)
  registerTaskRoutes(app, taskService)

  registerAgentExecutionRoutes(app, agentExecutionService, gateway)

  app.get("/status", { logLevel: "silent", schema: {
    tags: ["Status"], summary: "Get backend and agent-server availability",
    description: "Always returns 200 while the backend handles requests. agentServer is unknown without a configured URL, online on a successful probe, or offline on failure/timeout (2000 ms).",
    response: { 200: {
      type: "object", required: ["status", "service", "agentServer"],
      properties: {
        status: { type: "string", enum: ["ok"] },
        service: { type: "string", enum: ["backend"] },
        agentServer: { type: "string", enum: ["online", "offline", "unknown"] },
      },
    } },
  } }, async () => {
    return { status: "ok", service: "backend", agentServer: await checkAgentServer(options.agentServerUrl) }
  })

  return { app, db }
}

/** The agent-server serves this under /api, same as its run endpoint. */
const AGENT_STATUS_PATH = "/api/status"

/** index.ts passes the URL from PORT_AGENTSERVER. Without it there is nowhere to
 *  send an agent, so the run fails with that reason instead of hanging. The URL
 *  is not defaulted here on purpose: reading env in this file would make
 *  building the app depend on a .env being present, which the tests do not have. */
function buildAgentInvoker(url: string | undefined): AgentInvoker {
  if (url === undefined || url === "") {
    return {
      run: async () => {
        throw new Error("No agent server url is configured")
      },
    }
  }

  return new AgentServerClient(url)
}

async function checkAgentServer(url: string | undefined): Promise<string> {
  if (url === undefined) {
    return "unknown"
  }
  try {
    const response = await fetch(`${url}${AGENT_STATUS_PATH}`, { signal: AbortSignal.timeout(2000) })
    return response.ok ? "online" : "offline"
  } catch {
    return "offline"
  }
}

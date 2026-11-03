import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { createServer } from "node:http"
import { once } from "node:events"
import type { AddressInfo } from "node:net"
import { setTimeout } from "node:timers/promises"
import { buildApp } from "../app.js"
import { ProjectGraphService } from "../modules/project-graph/project-graph.service.js"
import { ProjectRepository } from "../modules/project/project.repository.js"
import { TaskRepository } from "../modules/task/task.repository.js"
import { TaskRunner } from "../infrastructure/task-runner/task.runner.js"
import { serviceTaskExecutor } from "../infrastructure/task-runner/service.task-executor.js"
import { RealtimeGateway } from "../infrastructure/realtime-gateway/realtime.gateway.js"

it("runs Graphify as a detached Task, persists callback state and isolates it from audit execution", { timeout: 30000 }, async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-project-graph-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execSync("pnpm prisma migrate deploy", { cwd: fileURLToPath(new URL("../../", import.meta.url)),
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore" })
  const requests: Array<{ task_id: number, callback_token: string, commit_hash: string, branch: string, repository_path: string }> = []
  const remote = createServer(async (request, response) => {
    if (request.method === "POST" && request.url === "/api/graphs") {
      let body = ""
      for await (const chunk of request) body += chunk
      requests.push(JSON.parse(body))
      response.writeHead(202, { "Content-Type": "application/json" }).end('{"accepted":true}')
    } else if (request.url?.endsWith("/artifact")) {
      response.writeHead(200, { "Content-Type": "application/json" }).end('{"nodes":[],"edges":[]}')
    } else response.writeHead(404).end()
  })
  remote.listen(0, "127.0.0.1")
  await once(remote, "listening")
  const options = { databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    agentServerUrl: `http://127.0.0.1:${(remote.address() as AddressInfo).port}` }
  const { app, db } = await buildApp(options)
  try {
    await app.ready()
    const project = await db.project.create({ data: { repositoryOwner: "acme", repositoryName: "graph", status: "READY" } })
    const url = `/api/projects/${project.id}/graph`
    const response = await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "a".repeat(40) } })
    assert.equal(response.statusCode, 202, response.body)
    const taskId = response.json().taskId as number
    const duplicate = await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "a".repeat(40) } })
    assert.equal(duplicate.json().taskId, taskId)
    for (let attempt = 0; requests.length === 0 && attempt < 100; attempt++) await setTimeout(10)
    assert.equal(requests.length, 1)
    assert.equal(requests[0]!.commit_hash, "a".repeat(40))
    assert.equal(requests[0]!.branch, "main")
    assert.ok(requests[0]!.repository_path.startsWith(options.workspaceDir))
    assert.equal((await db.task.findUniqueOrThrow({ where: { id: taskId } })).status, "Running")
    assert.equal(await db.agentExecution.count(), 0)
    assert.equal(await db.evaluation.count(), 0)
    assert.equal((await app.inject({ url: "/api/tasks/active" })).json()[0].kind, "graph.extract")
    const callback = (phase: string, token = requests[0]!.callback_token) => app.inject({ method: "POST",
      url: `/api/tasks/${taskId}/graph-callback`, headers: { "x-graph-token": token }, payload: { phase } })
    assert.equal((await callback("completed", "wrong-token")).statusCode, 403)
    const socket = await app.injectWS("/ws")
    try {
      const next = once(socket, "message", { signal: AbortSignal.timeout(5000) })
      assert.equal((await callback("extracting")).statusCode, 200)
      const [message] = await next
      const event = JSON.parse(String(message))
      assert.equal(event.type, "task.updated")
      assert.equal(event.task.id, taskId)
      assert.equal(event.task.status, "Running")
      assert.ok(!String(message).includes(requests[0]!.callback_token))
    } finally { socket.terminate() }
    await callback("preparing")
    assert.equal((await app.inject({ url })).json().phase, "extracting")
    assert.equal((await app.inject({ url: `${url}/${taskId}/artifact` })).statusCode, 404)
    await callback("completed")
    for (let attempt = 0; attempt < 100; attempt++) {
      if ((await db.task.findUniqueOrThrow({ where: { id: taskId } })).status === "Succeded") break
      await setTimeout(10)
    }
    const completed = (await app.inject({ url })).json()
    assert.equal(completed.status, "Succeded")
    assert.equal(completed.graphAvailable, true)
    assert.ok(!JSON.stringify(completed).includes(requests[0]!.callback_token))
    assert.equal((await callback("completed")).statusCode, 200)
    assert.equal((await callback("failed")).statusCode, 200)
    assert.equal((await app.inject({ url })).json().phase, "completed")
    assert.equal((await app.inject({ url: `${url}/${taskId}/artifact` })).body, '{"nodes":[],"edges":[]}')
    assert.equal((await app.inject({ url: `/api/projects/${project.id + 1}/graph/${taskId}/artifact` })).statusCode, 404)
    assert.equal((await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "HEAD" } })).statusCode, 400)

    const cached = await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "a".repeat(40) } })
    assert.equal(cached.json().taskId, taskId)
    assert.equal(cached.json().reused, true)
    assert.equal(await db.task.count(), 1, "reusing a completed graph must not create a new task")
    assert.equal(requests.length, 1)

    const regenerated = await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "a".repeat(40), regenerate: true } })
    const regeneratedId = regenerated.json().taskId as number
    assert.notEqual(regeneratedId, taskId)
    for (let attempt = 0; !requests.some((item) => item.task_id === regeneratedId) && attempt < 100; attempt++) await setTimeout(10)
    const regeneration = requests.find((item) => item.task_id === regeneratedId)!
    assert.ok(regeneration)
    assert.equal((await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "a".repeat(40), regenerate: true } })).json().taskId, regeneratedId)
    const failureUrl = `/api/tasks/${regeneratedId}/graph-callback`
    assert.equal((await app.inject({ method: "POST", url: failureUrl, headers: { "x-graph-token": regeneration.callback_token },
      payload: { phase: "failed", errorCode: "private untrusted exception" } })).statusCode, 400)
    await app.inject({ method: "POST", url: failureUrl, headers: { "x-graph-token": regeneration.callback_token },
      payload: { phase: "failed", errorCode: "storage_failed" } })
    for (let attempt = 0; attempt < 100; attempt++) {
      if ((await db.task.findUniqueOrThrow({ where: { id: regeneratedId } })).status === "Failed") break
      await setTimeout(10)
    }
    const failed = (await app.inject({ url })).json()
    assert.equal(failed.error, "storage_failed", "the callback's safe failure category must survive executor cleanup")
    assert.equal(failed.graphAvailable, false)
    assert.equal(failed.previousGraphTaskId, taskId)
    assert.equal((await app.inject({ url: `${url}/${regeneratedId}/artifact` })).statusCode, 404)
    assert.equal((await app.inject({ url: `${url}/${taskId}/artifact` })).statusCode, 200, "a failed regeneration must preserve the previous valid artifact")

    const retry = await app.inject({ method: "POST", url, payload: { branch: "main", commitHash: "a".repeat(40), regenerate: true } })
    const retryId = retry.json().taskId as number
    assert.notEqual(retryId, regeneratedId)
    for (let attempt = 0; !requests.some((item) => item.task_id === retryId) && attempt < 100; attempt++) await setTimeout(10)
    const retried = requests.find((item) => item.task_id === retryId)!
    await app.inject({ method: "POST", url: `/api/tasks/${retryId}/graph-callback`, headers: { "x-graph-token": retried.callback_token }, payload: { phase: "completed" } })
    for (let attempt = 0; attempt < 100; attempt++) {
      if ((await db.task.findUniqueOrThrow({ where: { id: retryId } })).status === "Succeded") break
      await setTimeout(10)
    }
    assert.equal((await app.inject({ url })).json().graphAvailable, true)

    // A lost terminal callback must release the executor and fail durably.
    const tasks = new TaskRepository(db)
    const projects = new ProjectRepository(db)
    const gateway = new RealtimeGateway()
    const service = new ProjectGraphService(db, tasks, projects, gateway, options.workspaceDir, options.agentServerUrl, 30)
    const runner = new TaskRunner(tasks, projects, gateway, [serviceTaskExecutor({ "graph.extract": service.handler() })])
    const timed = await service.start(project.id, "main", "b".repeat(40), runner)
    for (let attempt = 0; attempt < 100; attempt++) {
      if ((await service.get(project.id, timed!.taskId))?.status === "Failed") break
      await setTimeout(10)
    }
    assert.equal((await service.get(project.id, timed!.taskId))?.status, "Failed")
    assert.equal((await service.get(project.id, timed!.taskId))?.error, "timeout")
    const orphan = await tasks.create({ projectId: project.id, description: "Interrupted graph", kind: "graph.extract", status: "Running" })
    await db.graphExtraction.create({ data: { taskId: orphan.id, projectId: project.id, branch: "main", commitHash: "c".repeat(40) } })
    await service.reconcile()
    assert.equal((await service.get(project.id, orphan.id))?.status, "Failed")
    assert.equal((await service.get(project.id, orphan.id))?.error, "interrupted")
    assert.equal(await db.agentExecution.count(), 0)
  } finally {
    await app.close()
    await db.$disconnect()
    remote.closeAllConnections()
    await new Promise<void>((resolve) => remote.close(() => resolve()))
  }
})

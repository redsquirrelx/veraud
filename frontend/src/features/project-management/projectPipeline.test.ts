import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { getProjectGraph, startProjectGraph, type ProjectGraph } from "./projectGraphApi.ts"
import { PROJECT_PIPELINE, architectureContextStep, runProjectPipeline, structuralGraphStep, type ProjectPipelineStep } from "./projectPipeline.ts"
import { startArchitectureContext, getArchitectureContextExecution } from "./architectureContextApi.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { ProjectPipelineError } from "./projectPipelineErrors.ts"

vi.mock("./projectGraphApi.ts", () => ({ getProjectGraph: vi.fn(), startProjectGraph: vi.fn() }))
vi.mock("./architectureContextApi.ts", () => ({ startArchitectureContext: vi.fn(), getArchitectureContextExecution: vi.fn() }))
const context = { projectId: 2, branch: "main", commitHash: "a".repeat(40) }
const running: ProjectGraph = { ...context, taskId: 8, status: "Running", phase: "extracting", graphAvailable: false, error: null }
const completed: ProjectGraph = { ...running, status: "Succeded", phase: "completed", graphAvailable: true }
const contextOutput = { schema_version: "1", execution_status: "partial", document_index: { commit: context.commitHash } }
const waitingContext = { id: 42, agentType: "architecture_context", evaluationId: 10, status: "Running", result: null } as AgentExecution
const completedContext = { ...waitingContext, status: "Completed", result: JSON.stringify(contextOutput) } as AgentExecution

beforeEach(() => vi.resetAllMocks())
afterEach(() => vi.useRealTimers())

describe("project pipeline", () => {
  it("reuses an existing graph and reaches context; a missing model is not reported as a graph failure", async () => {
    vi.mocked(getProjectGraph).mockResolvedValue(completed)
    vi.mocked(startArchitectureContext).mockRejectedValue(new ProjectPipelineError("analyze.pipeline.contextConfigurationError"))
    const progress = vi.fn()
    await expect(runProjectPipeline(PROJECT_PIPELINE, context, new AbortController().signal, progress)).rejects
      .toMatchObject({ labelKey: "analyze.pipeline.contextConfigurationError" })
    expect(startProjectGraph).not.toHaveBeenCalled()
    expect(startArchitectureContext).toHaveBeenCalledOnce()
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ index: 2, stepId: "architecture-context" }))
    vi.mocked(startArchitectureContext).mockResolvedValue(completedContext)
    expect((await runProjectPipeline(PROJECT_PIPELINE, context, new AbortController().signal, vi.fn())).get("architecture-context"))
      .toEqual(contextOutput)
    expect(startProjectGraph).not.toHaveBeenCalled()
  })
  it("runs architecture context only after graph completion and awaits its persisted output", async () => {
    vi.useFakeTimers()
    vi.mocked(getProjectGraph).mockResolvedValueOnce(running).mockResolvedValue(completed)
    vi.mocked(startArchitectureContext).mockResolvedValue(waitingContext)
    vi.mocked(getArchitectureContextExecution).mockResolvedValue(completedContext)
    const progress = vi.fn()
    const controller = new AbortController()
    const pending = runProjectPipeline(PROJECT_PIPELINE, context, controller.signal, progress)
    await vi.advanceTimersByTimeAsync(0)
    expect(startArchitectureContext).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(3000)
    expect(startArchitectureContext).toHaveBeenCalledWith(context, controller.signal)
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ stepId: "architecture-context", index: 2, total: 2 }))
    expect(getArchitectureContextExecution).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(3000)
    expect((await pending).get("architecture-context")).toEqual(contextOutput)
  })

  it.each([
    { ...completedContext, result: null },
    { ...completedContext, result: JSON.stringify({ ...contextOutput, execution_status: "failed" }) },
    { ...completedContext, result: JSON.stringify({ ...contextOutput, document_index: { commit: "b".repeat(40) } }) },
    { ...completedContext, status: "Failed" as const },
    { ...completedContext, agentType: "architecture" },
    { ...completedContext, evaluationId: null },
  ])("stops without another step for failed or invalid context output: %j", async (execution) => {
    vi.mocked(startArchitectureContext).mockResolvedValue(execution)
    const next = vi.fn()
    await expect(runProjectPipeline([architectureContextStep, { id: "next", run: next }], context,
      new AbortController().signal, vi.fn())).rejects.toThrow()
    expect(next).not.toHaveBeenCalled()
  })

  it("aborts architecture-context tracking without another poll or subsequent step", async () => {
    vi.useFakeTimers()
    vi.mocked(startArchitectureContext).mockResolvedValue(waitingContext)
    const controller = new AbortController()
    const pending = architectureContextStep.run(context, new Map(), controller.signal)
    const failed = expect(pending).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    await failed
    await vi.advanceTimersByTimeAsync(6000)
    expect(getArchitectureContextExecution).not.toHaveBeenCalled()
  })

  it("passes results in order using a fixed revision, without starting later steps early", async () => {
    let finish!: (result: string) => void
    const next = vi.fn(async (snapshot, results) => {
      expect(snapshot).toEqual(context)
      expect(results.get("first")).toBe("artifact")
      return "next result"
    })
    const steps: ProjectPipelineStep[] = [
      { id: "first", run: () => new Promise<string>((resolve) => { finish = resolve }) },
      { id: "next", run: next },
    ]
    const progress = vi.fn()
    const input = { ...context }
    const pending = runProjectPipeline(steps, input, new AbortController().signal, progress)
    input.commitHash = "b".repeat(40)
    expect(next).not.toHaveBeenCalled()
    finish("artifact")
    expect((await pending).get("next")).toBe("next result")
    expect(progress.mock.calls.map(([value]) => value)).toEqual([
      { stepId: "first", index: 1, total: 2 }, { stepId: "next", index: 2, total: 2 },
    ])
  })

  it("stops on errors and rejects duplicate step IDs before any work", async () => {
    const next = vi.fn()
    const steps = [{ id: "first", run: async () => { throw new Error("failed") } }, { id: "next", run: next }]
    await expect(runProjectPipeline(steps, context, new AbortController().signal, vi.fn())).rejects.toThrow("failed")
    expect(next).not.toHaveBeenCalled()
    await expect(runProjectPipeline([steps[1]!, steps[1]!], context, new AbortController().signal, vi.fn())).rejects.toThrow("Duplicate")
    expect(next).not.toHaveBeenCalled()
  })

  it("waits for a completed artifact, not the graph submission", async () => {
    vi.useFakeTimers()
    vi.mocked(getProjectGraph).mockResolvedValueOnce(null).mockResolvedValue(completed)
    vi.mocked(startProjectGraph).mockResolvedValue(running)
    const next = vi.fn(async () => "done")
    const pending = runProjectPipeline([structuralGraphStep, { id: "next", run: next }], context, new AbortController().signal, vi.fn())
    await vi.advanceTimersByTimeAsync(0)
    expect(startProjectGraph).toHaveBeenCalledOnce()
    expect(next).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(3000)
    expect((await pending).get("structural-graph")).toEqual(completed)
    expect(next).toHaveBeenCalledOnce()
  })

  it("reuses a saved artifact and adopts running tasks without submitting duplicates", async () => {
    vi.mocked(getProjectGraph).mockResolvedValue(completed)
    await expect(structuralGraphStep.run(context, new Map(), new AbortController().signal)).resolves.toEqual(completed)
    expect(startProjectGraph).not.toHaveBeenCalled()
    vi.useFakeTimers()
    vi.mocked(getProjectGraph).mockResolvedValueOnce(running).mockResolvedValue(completed)
    const pending = structuralGraphStep.run(context, new Map(), new AbortController().signal)
    await vi.advanceTimersByTimeAsync(3000)
    await expect(pending).resolves.toEqual(completed)
    expect(startProjectGraph).not.toHaveBeenCalled()
  })

  it.each([
    { ...running, status: "Failed" as const, graphAvailable: true, previousGraphTaskId: 7 },
    { ...completed, graphAvailable: false },
    { ...completed, commitHash: "b".repeat(40) },
    { ...completed, taskId: 9 },
  ])("does not continue with failed, missing, stale or replaced artifacts: %j", async (terminal) => {
    vi.useFakeTimers()
    vi.mocked(getProjectGraph).mockResolvedValueOnce(running).mockResolvedValue(terminal)
    const next = vi.fn()
    const pending = runProjectPipeline([structuralGraphStep, { id: "next", run: next }], context, new AbortController().signal, vi.fn())
    const failed = expect(pending).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(3000)
    await failed
    expect(next).not.toHaveBeenCalled()
  })

  it("aborts waiting and never starts subsequent steps", async () => {
    vi.useFakeTimers()
    vi.mocked(getProjectGraph).mockResolvedValue(running)
    const next = vi.fn()
    const controller = new AbortController()
    const pending = runProjectPipeline([structuralGraphStep, { id: "next", run: next }], context, controller.signal, vi.fn())
    const failed = expect(pending).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    await failed
    await vi.advanceTimersByTimeAsync(9000)
    expect(getProjectGraph).toHaveBeenCalledOnce()
    expect(next).not.toHaveBeenCalled()
  })
})

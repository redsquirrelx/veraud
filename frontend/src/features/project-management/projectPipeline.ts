/** Frontend-only sequential orchestration. Closing the page stops orchestration,
 * not backend tasks already submitted. Add steps to PROJECT_PIPELINE below. */
import { getProjectGraph, startProjectGraph, type ProjectGraph } from "./projectGraphApi.ts"
import type { ParseKeys } from "i18next"
import { startArchitectureContext, getArchitectureContextExecution, type ArchitectureContextOutput } from "./architectureContextApi.ts"
import { ProjectPipelineError } from "./projectPipelineErrors.ts"

export interface ProjectPipelineContext {
  readonly projectId: number
  readonly branch: string
  readonly commitHash: string
}

export interface ProjectPipelineStep {
  id: string
  labelKey?: ParseKeys<"projects">
  failureKey?: ParseKeys<"projects">
  run: (context: ProjectPipelineContext, results: ReadonlyMap<string, unknown>, signal: AbortSignal) => Promise<unknown>
}

export interface ProjectPipelineProgress {
  stepId: string
  labelKey?: ParseKeys<"projects">
  index: number
  total: number
}

export async function runProjectPipeline(
  steps: readonly ProjectPipelineStep[], context: ProjectPipelineContext, signal: AbortSignal,
  onProgress: (progress: ProjectPipelineProgress) => void,
) {
  if (new Set(steps.map((step) => step.id)).size !== steps.length) throw new Error("Duplicate pipeline step")
  const snapshot = Object.freeze({ ...context })
  const results = new Map<string, unknown>()
  for (const [index, step] of steps.entries()) {
    signal.throwIfAborted()
    onProgress({ stepId: step.id, ...(step.labelKey ? { labelKey: step.labelKey } : {}), index: index + 1, total: steps.length })
    let output: unknown
    try {
      output = await step.run(snapshot, new Map(results), signal)
    } catch (error) {
      if (signal.aborted || error instanceof ProjectPipelineError || !step.failureKey) throw error
      throw new ProjectPipelineError(step.failureKey)
    }
    signal.throwIfAborted()
    results.set(step.id, output)
  }
  return results
}

function pause(signal: AbortSignal) {
  signal.throwIfAborted()
  return new Promise<void>((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve() }, 3000)
    signal.addEventListener("abort", abort, { once: true })
  })
}

function assertRevision(graph: ProjectGraph, context: ProjectPipelineContext) {
  if (graph.projectId !== context.projectId || graph.commitHash !== context.commitHash) {
    throw new Error("Graph revision mismatch")
  }
}

export const structuralGraphStep: ProjectPipelineStep = {
  id: "structural-graph",
  labelKey: "analyze.pipeline.structuralGraph",
  failureKey: "analyze.pipeline.graphStepFailed",
  async run(context, _results, signal) {
    const { projectId, branch, commitHash } = context
    let graph = await getProjectGraph(projectId, commitHash, signal)
    signal.throwIfAborted()
    if (graph) assertRevision(graph, context)
    if (!graph || graph.status === "Failed" || (graph.status === "Succeded" && !graph.graphAvailable)) {
      graph = await startProjectGraph(projectId, branch, commitHash, false, signal)
    }
    assertRevision(graph, context)
    const taskId = graph.taskId
    while (true) {
      signal.throwIfAborted()
      if (graph.status === "Failed") throw new Error("Graph extraction failed")
      if (graph.status === "Succeded") {
        if (!graph.graphAvailable) throw new Error("Graph artifact unavailable")
        return graph
      }
      await pause(signal)
      const next = await getProjectGraph(projectId, commitHash, signal)
      if (!next || next.taskId !== taskId) throw new Error("Graph task unavailable or replaced")
      assertRevision(next, context)
      graph = next
    }
  },
}

export const architectureContextStep: ProjectPipelineStep = {
  id: "architecture-context",
  labelKey: "analyze.pipeline.architectureContext",
  failureKey: "analyze.pipeline.contextStepFailed",
  async run(context, _results, signal): Promise<ArchitectureContextOutput> {
    signal.throwIfAborted()
    let execution = await startArchitectureContext(context, signal)
    const id = execution.id
    const evaluationId = execution.evaluationId
    while (true) {
      signal.throwIfAborted()
      if (execution.id !== id || execution.agentType !== "architecture_context" || evaluationId === null
        || execution.evaluationId !== evaluationId) throw new Error("Architecture context execution mismatch")
      if (execution.status === "Failed") throw new Error("Architecture context execution failed")
      if (execution.status === "Completed") {
        const output = JSON.parse(execution.result ?? "null") as ArchitectureContextOutput | null
        if (!output || output.schema_version !== "1" || output.document_index?.commit !== context.commitHash
          || !["complete", "partial", "failed"].includes(output.execution_status)) {
          throw new Error("Architecture context artifact unavailable or stale")
        }
        if (output.execution_status === "failed") throw new Error("Architecture context failed")
        // Completed is published only after the backend's artifact transaction.
        // Partial documentary coverage remains partial, not inferred compliance.
        return output
      }
      await pause(signal)
      execution = await getArchitectureContextExecution(id, signal)
    }
  },
}

/** Append subsequent steps here; their inputs include preceding step results. */
export const PROJECT_PIPELINE: readonly ProjectPipelineStep[] = [structuralGraphStep, architectureContextStep]

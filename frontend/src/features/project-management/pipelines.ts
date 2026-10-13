export interface PipelineOption {
  id: string
  label: string
  description: string
  /** Backend route suffix under /api/projects/:id/. */
  endpoint: "analyze" | "architecture"
  /** Stage rows in run order; the last one finishes last. */
  stages: string[]
  /** Row the UI tracks while the pipeline runs. */
  trackedStage: string
}

/** Pipelines the backend serves. Mirrors the agent-server registry; the
 *  backend has no listing endpoint, so this is explicit on purpose. */
export const PIPELINES: PipelineOption[] = [
  {
    id: "architecture-audit",
    label: "Classic audit",
    description: "Analyzer then architect",
    endpoint: "analyze",
    stages: ["analyzer", "architect"],
    trackedStage: "architect",
  },
  {
    id: "project-architecture",
    label: "Project architecture",
    description: "Orientation, architecture and semantic validation",
    endpoint: "architecture",
    stages: ["orientation", "architecture", "semantic_validation"],
    trackedStage: "semantic_validation",
  },
]

export const DEFAULT_PIPELINE_ID = PIPELINES[0]!.id

export function pipelineById(id: string): PipelineOption {
  return PIPELINES.find((option) => option.id === id) ?? PIPELINES[0]!
}

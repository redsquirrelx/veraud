import type { PrismaClient } from "../../generated/prisma/client.js"

export function architectureContextFixture(commit: string) {
  return { schema_version: "1", document_index: { index_id: "context-index", repository_id: "context-repository", commit },
    knowledge: [], knowledge_issues: [], covered_categories: [],
    pending_categories: ["architectural_style", "components", "responsibilities", "relationships", "constraints", "interfaces_and_contracts", "architectural_decisions"],
    evaluated_categories: [], coverage_assessment_status: "not_run", consulted_documents: [], section_paths: {},
    validation_errors: [], execution_status: "partial", finalization_reason: "incomplete_coverage", execution_error: null }
}

export async function seedArchitectureContext(db: PrismaClient, projectId: number, commitHash: string) {
  const result = architectureContextFixture(commitHash)
  await db.agentSettings.upsert({ where: { agentType: "architecture_context" }, create: { agentType: "architecture_context" }, update: {} })
  const version = await db.projectVersion.upsert({ where: { projectId_commitHash: { projectId, commitHash } },
    create: { projectId, branch: "main", commitHash, analysisStatus: "Completed" }, update: {} })
  const evaluation = await db.evaluation.create({ data: { projectVersionId: version.id, type: "ArchitectureContext" } })
  const execution = await db.agentExecution.create({ data: {
    evaluationId: evaluation.id, agentType: "architecture_context", status: "Completed", result: JSON.stringify(result),
  } })
  await db.architectureContextArtifact.create({ data: { executionId: execution.id, projectVersionId: version.id,
    schemaVersion: "1", executionStatus: "partial", result: JSON.stringify(result) } })
  return { result, executionId: execution.id, projectVersionId: version.id }
}

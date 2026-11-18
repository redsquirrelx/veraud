import { pathToFileURL, fileURLToPath } from "node:url"
import { dirname, join, resolve } from "node:path"
import { writeFileSync } from "node:fs"

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, "..", "..")
const importUrl = (path) => pathToFileURL(join(repoRoot, path)).href

const { PrismaClient } = await import(importUrl("backend/src/generated/prisma/client.ts"))
const { PrismaBetterSqlite3 } = await import(importUrl("backend/node_modules/@prisma/adapter-better-sqlite3/dist/index.mjs"))

/** Seeds the E2E template database. Runs from the backend directory so module
 *  resolution uses backend/node_modules. Beyond rows, it writes the created
 *  identifiers to a JSON file consumed by the Playwright suite. */

const databaseUrl = process.env.DATABASE_URL
const mainCommit = process.env.SEED_MAIN_COMMIT
const featureCommit = process.env.SEED_FEATURE_COMMIT
const statePath = process.env.SEED_STATE_PATH

if (!databaseUrl || !mainCommit || !featureCommit || !statePath) {
  console.error("seed.mjs: DATABASE_URL, SEED_MAIN_COMMIT, SEED_FEATURE_COMMIT and SEED_STATE_PATH are required")
  process.exit(1)
}

const db = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url: databaseUrl }) })
const minutes = (n) => new Date(Date.now() - n * 60 * 1000)
const receipt = (partial) => ({
  parent_invocation_id: null,
  run_id: null,
  phase: null,
  phase_sequence: 0,
  unknown_usage_attempts: 0,
  error: null,
  ...partial,
})
const receipts = (items) => JSON.stringify(items)

async function seedAgentSettings() {
  const rows = [
    { agentType: "maintainability_manager", catalogDeclared: true, catalogName: "Maintainability", catalogRole: "manager", requiresModel: false, qualityAttributes: '["maintainability"]', executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "maintainability_coordinator", catalogDeclared: true, catalogName: "Maintainability coordinator", catalogRole: "coordinator", requiresModel: false, qualityAttributes: '["maintainability"]', executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "modularity", catalogDeclared: true, catalogName: "Modularity", catalogRole: "investigator", requiresModel: false, qualityAttributes: '["maintainability"]', executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "complexity", catalogDeclared: true, catalogName: "Complexity", catalogRole: "investigator", requiresModel: false, qualityAttributes: '["maintainability"]', executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "security", catalogDeclared: true, catalogName: "Security", catalogRole: "manager", requiresModel: false, qualityAttributes: '["security"]', executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "security_sast", catalogDeclared: true, catalogName: "SAST analysis", catalogRole: "investigator", requiresModel: false, qualityAttributes: '["security"]', executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "orientation", catalogDeclared: true, catalogName: "Orientation", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "architecture", catalogDeclared: true, catalogName: "Architecture analyzer", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "semantic_validation", catalogDeclared: true, catalogName: "Semantic validation", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "architecture_context", catalogDeclared: true, catalogName: "Architecture context", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "verification_suite", catalogDeclared: true, catalogName: "Verification suite", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "finding_test_generation", catalogDeclared: true, catalogName: "Finding test generation", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "testability_probe", catalogDeclared: true, catalogName: "Testability probe", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
    { agentType: "finding_resolution", catalogDeclared: true, catalogName: "Finding resolution", catalogRole: "agent", requiresModel: false, qualityAttributes: "[]", executionModes: '["live"]', workflowIds: "[]" },
  ]
  for (const row of rows) await db.agentSettings.create({ data: row })
}

async function main() {
  await seedAgentSettings()

  const project = await db.project.create({
    data: {
      id: 1,
      name: "Veraud E2E sandbox",
      status: "READY",
      createdAt: minutes(60 * 24 * 3),
      lastSyncedAt: minutes(60),
      githubRepositoryId: BigInt("9900000001"),
      cloneProtocol: "https",
      shallowClone: true,
      repositoryOwner: "e2e-owner",
      repositoryName: "e2e-sandbox",
    },
  })

  const mainVersion = await db.projectVersion.create({
    data: { projectId: project.id, branch: "main", commitHash: mainCommit, analysisStatus: "Completed", analyzedAt: minutes(60 * 24) },
  })
  const featureVersion = await db.projectVersion.create({
    data: { projectId: project.id, branch: "feature/sample", commitHash: featureCommit, analysisStatus: "Pending" },
  })
  await db.project.update({ where: { id: project.id }, data: { selectedVersionId: mainVersion.id } })

  const qualityAudit = (startedAgoMinutes) => db.evaluation.create({
    data: { projectVersionId: mainVersion.id, type: "QualityAudit", createdAt: minutes(startedAgoMinutes), startedAt: minutes(startedAgoMinutes - 1) },
  })

  const running = await qualityAudit(120)
  const joint = await qualityAudit(60 * 24)
  const failed = await qualityAudit(60 * 48)
  const cancelOnly = await qualityAudit(15)
  const architecture = await db.evaluation.create({
    data: { projectVersionId: mainVersion.id, type: "ArchitectureContext", createdAt: minutes(90), startedAt: minutes(89) },
  })
  const verificationSuite = await db.evaluation.create({
    data: { projectVersionId: mainVersion.id, type: "VerificationSuite", createdAt: minutes(30), startedAt: minutes(29) },
  })

  const runningAudit = await db.agentExecution.create({
    data: {
      evaluationId: running.id,
      agentType: "maintainability_manager",
      status: "Running",
      createdAt: minutes(120),
      startedAt: minutes(119),
      inputTokens: null,
      outputTokens: null,
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-manager", agent_id: "maintainability_manager", status: "running", phase: "investigate", started_at: minutes(119).toISOString(), finished_at: null, input_tokens: 600, output_tokens: 80, run_id: "e2e-run-101" }),
        receipt({ invocation_id: "inv-coordinator", agent_id: "maintainability_coordinator", parent_invocation_id: "inv-manager", status: "running", started_at: minutes(90).toISOString(), finished_at: null, input_tokens: 250, output_tokens: 30, run_id: "e2e-run-101" }),
        receipt({ invocation_id: "inv-modularity", agent_id: "modularity", parent_invocation_id: "inv-coordinator", status: "completed", started_at: minutes(88).toISOString(), finished_at: minutes(60).toISOString(), input_tokens: 120, output_tokens: 30, run_id: "e2e-run-101" }),
        receipt({ invocation_id: "inv-complexity", agent_id: "complexity", parent_invocation_id: "inv-coordinator", status: "running", phase: "synthesize_findings", started_at: minutes(88).toISOString(), finished_at: null, input_tokens: 130, output_tokens: 40, run_id: "e2e-run-101" }),
      ]),
      result: JSON.stringify({ attributes: ["maintainability"], run_id: "e2e-run-101", status: "running" }),
    },
  })

  const jointMaintainability = await db.agentExecution.create({
    data: {
      evaluationId: joint.id,
      agentType: "maintainability_manager",
      status: "Completed",
      createdAt: minutes(60 * 24),
      startedAt: minutes(60 * 24 - 1),
      finishedAt: minutes(60 * 24 - 110),
      inputTokens: 2000,
      outputTokens: 400,
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-joint-manager", agent_id: "maintainability_manager", status: "completed", started_at: minutes(60 * 24 - 1).toISOString(), finished_at: minutes(60 * 24 - 110).toISOString(), input_tokens: 2000, output_tokens: 400, run_id: "e2e-run-102" }),
      ]),
      result: JSON.stringify({ attributes: ["maintainability", "security"], status: "completed", run_id: "e2e-run-102" }),
    },
  })

  const jointSecurity = await db.agentExecution.create({
    data: {
      evaluationId: joint.id,
      agentType: "security",
      status: "Completed",
      createdAt: minutes(60 * 24),
      startedAt: minutes(60 * 24 - 1),
      finishedAt: minutes(60 * 24 - 100),
      inputTokens: 1500,
      outputTokens: 300,
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-joint-security", agent_id: "security", status: "completed", started_at: minutes(60 * 24 - 1).toISOString(), finished_at: minutes(60 * 24 - 100).toISOString(), input_tokens: 1500, output_tokens: 300, run_id: "e2e-run-103" }),
        receipt({ invocation_id: "inv-joint-sast", agent_id: "security_sast", parent_invocation_id: "inv-joint-security", status: "completed", started_at: minutes(60 * 24 - 5).toISOString(), finished_at: minutes(60 * 24 - 130).toISOString(), input_tokens: 900, output_tokens: 150, run_id: "e2e-run-103" }),
      ]),
      result: JSON.stringify({ attributes: ["maintainability", "security"], status: "completed", run_id: "e2e-run-103" }),
    },
  })

  const failedAudit = await db.agentExecution.create({
    data: {
      evaluationId: failed.id,
      agentType: "maintainability_manager",
      status: "Failed",
      createdAt: minutes(60 * 48),
      startedAt: minutes(60 * 48 - 1),
      finishedAt: minutes(60 * 48 - 360),
      inputTokens: null,
      outputTokens: null,
      error: "Audit failed",
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-failed-manager", agent_id: "maintainability_manager", status: "failed", started_at: minutes(60 * 48 - 1).toISOString(), finished_at: minutes(60 * 48 - 360).toISOString(), input_tokens: 700, output_tokens: 100, error: "execution_timeout", run_id: "e2e-run-104" }),
      ]),
      result: JSON.stringify({ attributes: ["maintainability"], status: "failed", run_id: "e2e-run-104" }),
    },
  })

  const architectureContext = await db.agentExecution.create({
    data: {
      evaluationId: architecture.id,
      agentType: "architecture_context",
      status: "Completed",
      createdAt: minutes(90),
      startedAt: minutes(89),
      finishedAt: minutes(70),
      inputTokens: 50,
      outputTokens: 12,
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-architecture-context", agent_id: "architecture_context", status: "completed", started_at: minutes(89).toISOString(), finished_at: minutes(70).toISOString(), input_tokens: 50, output_tokens: 12, run_id: "e2e-run-201" }),
      ]),
      result: JSON.stringify({ status: "complete", execution_status: "complete", run_id: "e2e-run-201" }),
    },
  })

  // Dedicated running audit for the cancellation flow: the cancel test
  // permanently persists its own mutation, so other scenarios must not observe it.
  const cancelAudit = await db.agentExecution.create({
    data: {
      evaluationId: cancelOnly.id,
      agentType: "maintainability_manager",
      status: "Running",
      createdAt: minutes(15),
      startedAt: minutes(14),
      inputTokens: null,
      outputTokens: null,
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-cancel-manager", agent_id: "maintainability_manager", status: "running", phase: "investigate", started_at: minutes(14).toISOString(), finished_at: null, input_tokens: 100, output_tokens: 20, run_id: "e2e-run-901" }),
      ]),
      result: JSON.stringify({ attributes: ["maintainability"], status: "running", run_id: "e2e-run-901" }),
    },
  })

  const verificationSuiteRun = await db.agentExecution.create({
    data: {
      evaluationId: verificationSuite.id,
      agentType: "verification_suite",
      status: "Running",
      createdAt: minutes(30),
      startedAt: minutes(29),
      inputTokens: null,
      outputTokens: null,
      invocationReceipts: receipts([
        receipt({ invocation_id: "inv-suite-root", agent_id: "verification_suite", status: "running", phase: "generation", started_at: minutes(29).toISOString(), finished_at: null, input_tokens: null, output_tokens: null, run_id: "e2e-run-501" }),
        receipt({ invocation_id: "inv-suite-ftg", agent_id: "finding_test_generation", parent_invocation_id: "inv-suite-root", status: "completed", phase: "generation", started_at: minutes(28).toISOString(), finished_at: minutes(10).toISOString(), input_tokens: 9000, output_tokens: 510, run_id: "e2e-run-501" }),
        receipt({ invocation_id: "inv-suite-probe", agent_id: "testability_probe", parent_invocation_id: "inv-suite-root", status: "running", phase: "generation", phase_sequence: 1, started_at: minutes(28).toISOString(), finished_at: null, input_tokens: 7000, output_tokens: 430, run_id: "e2e-run-501" }),
      ]),
      result: JSON.stringify({ run_id: "e2e-run-501", status: "running" }),
    },
  })

  writeFileSync(statePath, JSON.stringify({
    projectId: project.id,
    mainVersionId: mainVersion.id,
    featureVersionId: featureVersion.id,
    mainCommit,
    featureCommit,
    evaluations: {
      runningAudit: running.id,
      jointCompleted: joint.id,
      failedAudit: failed.id,
      cancelAudit: cancelOnly.id,
      architectureContext: architecture.id,
      verificationSuite: verificationSuite.id,
    },
    executions: {
      runningAudit: runningAudit.id,
      jointCompletedMaintainability: jointMaintainability.id,
      jointCompletedSecurity: jointSecurity.id,
      failedAudit: failedAudit.id,
      cancelAudit: cancelAudit.id,
      architectureContext: architectureContext.id,
      verificationSuite: verificationSuiteRun.id,
    },
  }, null, 2))
}

main()
  .catch((error) => { console.error(error); process.exit(1) })
  .finally(() => db.$disconnect())

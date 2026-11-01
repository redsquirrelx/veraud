import type { AuditAgentRun, AuditPipelineRun } from "../../shared/audit-monitor/auditStatus.ts"

// Fixture of the catalog's display names; never fetch the live catalog for a DEMO.
const demoAgentNames: Record<string, string> = {
  maintainability_manager: "Gestor de mantenibilidad",
  modularity: "Coordinador de modularidad",
  responsibility: "Investigador de responsabilidades",
  dependency_impact: "Investigador de impacto de dependencias",
  testability: "Coordinador de capacidad de prueba",
  test_isolation: "Investigador de aislamiento de pruebas",
  security: "Coordinador de seguridad",
}

function execution(id: string, agentType: string, role: string, parentId: string | null,
  state: AuditAgentRun["state"], startedAt: string | null, finishedAt: string | null): AuditAgentRun {
  return { id, agentType, name: demoAgentNames[agentType], role, parentId, state, startedAt, finishedAt, error: null,
    inputTokens: startedAt ? 1200 : null, outputTokens: startedAt ? 240 : null }
}

/** Isolated DEMO invocations using the right-hand monitor's contract. No HTTP requests.
 * Remove this file and its import/use in AuditChronologyTab to remove the preview. */
export const demoChronologyPipelines: AuditPipelineRun[] = [
  { id: "maintainability", state: "running", agents: [
    execution("demo-manager", "maintainability_manager", "manager", null, "running", "2026-10-30T10:00:00Z", null),
    execution("demo-modularity", "modularity", "coordinator", "demo-manager", "completed", "2026-10-30T10:00:05Z", "2026-10-30T10:02:00Z"),
    execution("demo-responsibility-1", "responsibility", "investigator", "demo-modularity", "partial", "2026-10-30T10:00:12Z", "2026-10-30T10:01:10Z"),
    execution("demo-dependency", "dependency_impact", "investigator", "demo-modularity", "completed", "2026-10-30T10:00:14Z", "2026-10-30T10:01:50Z"),
    execution("demo-responsibility-2", "responsibility", "investigator", "demo-modularity", "completed", "2026-10-30T10:01:20Z", "2026-10-30T10:01:55Z"),
    execution("demo-testability", "testability", "coordinator", "demo-manager", "running", "2026-10-30T10:01:30Z", null),
    execution("demo-pending", "test_isolation", "investigator", "demo-testability", "waiting", null, null),
  ] },
  { id: "security", state: "completed", agents: [
    execution("demo-security", "security", "coordinator", null, "completed", "2026-10-30T10:00:06Z", "2026-10-30T10:01:40Z"),
  ] },
]

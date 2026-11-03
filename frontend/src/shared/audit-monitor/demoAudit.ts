import type { AuditStatusModel } from "./auditStatus.ts"

/** Temporary UI preview. Remove this file and its import/use in LiveAuditMonitor to remove the demo. */
export const demoAudit: AuditStatusModel = {
  demo: true,
  canCancel: true,
  id: -1,
  project: { id: -1, repositoryOwner: "DEMO", repositoryName: "DEMO" },
  branch: "demo",
  commitHash: null,
  state: "running",
  error: null,
  createdAt: "2026-10-29T12:00:00Z",
  finishedAt: null,
  reportAvailable: false,
  pipelines: [{
    id: "security",
    state: "running",
    agents: [{
      id: "demo-security",
      agentType: "security",
      name: "DEMO",
      state: "running",
      phase: "investigate",
      inputTokens: 0,
      outputTokens: 0,
      startedAt: "2026-10-29T12:00:00Z",
      finishedAt: null,
      error: null,
    }],
  }],
}

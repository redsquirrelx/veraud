import type { AuditStatusModel } from "./auditStatus.ts"

/** Isolated failed UI preview; no real execution. Remove this file and its import/use in LiveAuditMonitor to remove the demo. */
export const demoAudit: AuditStatusModel = {
  demo: true,
  canCancel: false,
  id: -2,
  project: { id: -1, repositoryOwner: "DEMO", repositoryName: "DEMO" },
  branch: "demo",
  commitHash: null,
  state: "failed",
  error: "Ejemplo DEMO: la auditoría no pudo completarse porque falló el agente de seguridad. No se ha realizado ninguna petición real.",
  createdAt: "2026-10-29T12:00:00Z",
  finishedAt: "2026-10-29T12:02:00Z",
  reportAvailable: false,
  pipelines: [{
    id: "security",
    state: "failed",
    agents: [{
      id: "demo-failed-security",
      agentType: "security",
      name: "DEMO",
      state: "failed",
      phase: null,
      inputTokens: 0,
      outputTokens: 0,
      startedAt: "2026-10-29T12:00:00Z",
      finishedAt: "2026-10-29T12:02:00Z",
      error: "Ejemplo DEMO: se agotó el tiempo de espera del proveedor durante el análisis de seguridad (TimeoutError).",
    }],
  }],
}

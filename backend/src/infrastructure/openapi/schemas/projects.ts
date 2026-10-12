export const projectSummarySchema = {
  $id: "ProjectSummary",
  type: "object",
  required: ["id", "repositoryOwner", "repositoryName", "cloneProtocol", "status", "registeredAt", "lastSyncedAt", "branch", "commitHash"],
  properties: {
    id: { type: "integer" },
    repositoryOwner: { type: "string" },
    repositoryName: { type: "string" },
    cloneProtocol: { type: "string", enum: ["https", "ssh"] },
    status: { type: "string" },
    registeredAt: { type: "string", format: "date-time" },
    lastSyncedAt: { type: ["string", "null"], format: "date-time" },
    branch: { type: ["string", "null"] },
    commitHash: { type: ["string", "null"] },
  },
} as const

export const registeredProjectSchema = {
  $id: "RegisteredProject",
  description: "Initial project snapshot returned after cloning succeeds; the persisted status may already have advanced.",
  type: "object",
  required: ["id", "repositoryOwner", "repositoryName", "status"],
  properties: {
    id: { type: "integer" },
    repositoryOwner: { type: "string" },
    repositoryName: { type: "string" },
    status: { type: "string" },
  },
} as const

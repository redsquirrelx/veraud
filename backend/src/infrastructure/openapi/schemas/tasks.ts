export const taskSchema = {
  $id: "Task",
  description: "HTTP task representation, including repository names; WebSocket task events have a different shape.",
  type: "object",
  required: ["id", "projectId", "repositoryOwner", "repositoryName", "description", "command", "status", "kind", "exitCode"],
  properties: {
    id: { type: "integer" },
    projectId: { type: "integer" },
    repositoryOwner: { type: "string" },
    repositoryName: { type: "string" },
    description: { type: ["string", "null"] },
    command: { type: ["string", "null"], description: "Readable executable and arguments, not a shell script. Null when no command was recorded." },
    status: { type: "string", enum: ["Queued", "Running", "Succeded", "Failed"] },
    kind: { type: "string" },
    exitCode: { type: ["integer", "null"] },
  },
} as const

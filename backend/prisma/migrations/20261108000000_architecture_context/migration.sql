CREATE TABLE "architecture_context_artifact" (
    "execution_id" INTEGER NOT NULL PRIMARY KEY,
    "project_version_id" INTEGER NOT NULL,
    "schema_version" TEXT NOT NULL,
    "execution_status" TEXT NOT NULL,
    "result" TEXT NOT NULL,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "architecture_context_artifact_execution_id_fkey" FOREIGN KEY ("execution_id") REFERENCES "agent_execution" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "architecture_context_artifact_project_version_id_fkey" FOREIGN KEY ("project_version_id") REFERENCES "project_version" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);
CREATE INDEX "architecture_context_artifact_project_version_id_execution_id_idx" ON "architecture_context_artifact"("project_version_id", "execution_id");

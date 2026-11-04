CREATE TABLE "graph_extraction" (
    "task_id" INTEGER NOT NULL PRIMARY KEY,
    "project_id" INTEGER NOT NULL,
    "branch" TEXT NOT NULL,
    "commit_hash" TEXT NOT NULL,
    "phase" TEXT NOT NULL DEFAULT 'queued',
    "error" TEXT,
    "callback_hash" TEXT,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "graph_extraction_task_id_fkey" FOREIGN KEY ("task_id") REFERENCES "task" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX "graph_extraction_project_id_commit_hash_task_id_idx" ON "graph_extraction"("project_id", "commit_hash", "task_id");

-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_agent_execution" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "evaluation_id" INTEGER,
    "agent_type" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at" DATETIME,
    "finished_at" DATETIME,
    "input_tokens" INTEGER,
    "output_tokens" INTEGER,
    "error" TEXT,
    "result" TEXT,
    CONSTRAINT "agent_execution_evaluation_id_fkey" FOREIGN KEY ("evaluation_id") REFERENCES "evaluation" ("id") ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT "agent_execution_agent_type_fkey" FOREIGN KEY ("agent_type") REFERENCES "agent_settings" ("agent_type") ON DELETE RESTRICT ON UPDATE CASCADE
);
INSERT INTO "new_agent_execution" ("agent_type", "created_at", "error", "evaluation_id", "finished_at", "id", "input_tokens", "output_tokens", "result", "started_at", "status") SELECT "agent_type", "created_at", "error", "evaluation_id", "finished_at", "id", "input_tokens", "output_tokens", "result", "started_at", "status" FROM "agent_execution";
DROP TABLE "agent_execution";
ALTER TABLE "new_agent_execution" RENAME TO "agent_execution";
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;

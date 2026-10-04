-- RedefineTables
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_task" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "project_id" INTEGER NOT NULL,
    "description" TEXT,
    "status" TEXT NOT NULL,
    "kind" TEXT NOT NULL DEFAULT 'unknown',
    "exit_code" INTEGER,
    "log_trail" TEXT,
    CONSTRAINT "task_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "project" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);
INSERT INTO "new_task" ("description", "exit_code", "id", "log_trail", "project_id", "status") SELECT "description", "exit_code", "id", "log_trail", "project_id", "status" FROM "task";
DROP TABLE "task";
ALTER TABLE "new_task" RENAME TO "task";
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;

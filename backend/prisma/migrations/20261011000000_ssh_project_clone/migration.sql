PRAGMA foreign_keys=OFF;

CREATE TABLE "new_project" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" TEXT,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_synced_at" DATETIME,
    "status" TEXT NOT NULL,
    "github_repository_id" BIGINT,
    "clone_protocol" TEXT NOT NULL DEFAULT 'https',
    "repository_owner" TEXT NOT NULL,
    "repository_name" TEXT NOT NULL,
    "selected_version_id" INTEGER,
    CONSTRAINT "project_selected_version_id_fkey" FOREIGN KEY ("selected_version_id") REFERENCES "project_version" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

INSERT INTO "new_project" ("id", "name", "created_at", "last_synced_at", "status", "github_repository_id", "repository_owner", "repository_name", "selected_version_id")
SELECT "id", "name", "created_at", "last_synced_at", "status", "github_repository_id", "repository_owner", "repository_name", "selected_version_id" FROM "project";

DROP TABLE "project";
ALTER TABLE "new_project" RENAME TO "project";
CREATE UNIQUE INDEX "project_github_repository_id_key" ON "project"("github_repository_id");
CREATE UNIQUE INDEX "project_selected_version_id_key" ON "project"("selected_version_id");
CREATE UNIQUE INDEX "project_repository_owner_repository_name_key" ON "project"("repository_owner", "repository_name");

PRAGMA foreign_key_check;
PRAGMA foreign_keys=ON;

/*
  Warnings:

  - You are about to drop the `Project` table. If the table is not empty, all the data it contains will be lost.

*/
-- DropTable
PRAGMA foreign_keys=off;
DROP TABLE "Project";
PRAGMA foreign_keys=on;

-- CreateTable
CREATE TABLE "project" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" TEXT,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_synced_at" DATETIME,
    "status" TEXT NOT NULL,
    "github_repository_id" BIGINT NOT NULL,
    "repository_owner" TEXT NOT NULL,
    "repository_name" TEXT NOT NULL,
    "selected_version_id" INTEGER,
    CONSTRAINT "project_selected_version_id_fkey" FOREIGN KEY ("selected_version_id") REFERENCES "project_version" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "project_version" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "project_id" INTEGER NOT NULL,
    "branch" TEXT,
    "commit_hash" TEXT,
    "analysis_status" TEXT NOT NULL,
    "analyzed_at" DATETIME,
    CONSTRAINT "project_version_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "project" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "evaluation" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "project_version_id" INTEGER NOT NULL,
    "type" TEXT NOT NULL,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at" DATETIME,
    "finished_at" DATETIME,
    CONSTRAINT "evaluation_project_version_id_fkey" FOREIGN KEY ("project_version_id") REFERENCES "project_version" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "agent_execution" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "evaluation_id" INTEGER NOT NULL,
    "agent_type" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "started_at" DATETIME,
    "finished_at" DATETIME,
    "input_tokens" INTEGER,
    "output_tokens" INTEGER,
    "error" TEXT,
    CONSTRAINT "agent_execution_evaluation_id_fkey" FOREIGN KEY ("evaluation_id") REFERENCES "evaluation" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "agent_execution_agent_type_fkey" FOREIGN KEY ("agent_type") REFERENCES "agent_settings" ("agent_type") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "ai_provider" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL
);

-- CreateTable
CREATE TABLE "ai_credential" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "ai_provider_id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "api_key" TEXT NOT NULL,
    CONSTRAINT "ai_credential_ai_provider_id_fkey" FOREIGN KEY ("ai_provider_id") REFERENCES "ai_provider" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "ai_model" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "ai_provider_id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    CONSTRAINT "ai_model_ai_provider_id_fkey" FOREIGN KEY ("ai_provider_id") REFERENCES "ai_provider" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "agent_settings" (
    "agent_type" TEXT NOT NULL PRIMARY KEY,
    "ai_model_id" INTEGER NOT NULL,
    "ai_credential_id" INTEGER NOT NULL,
    "temperature" DECIMAL,
    "max_tokens" INTEGER,
    CONSTRAINT "agent_settings_ai_model_id_fkey" FOREIGN KEY ("ai_model_id") REFERENCES "ai_model" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "agent_settings_ai_credential_id_fkey" FOREIGN KEY ("ai_credential_id") REFERENCES "ai_credential" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "project_github_repository_id_key" ON "project"("github_repository_id");

-- CreateIndex
CREATE UNIQUE INDEX "project_selected_version_id_key" ON "project"("selected_version_id");

-- CreateIndex
CREATE UNIQUE INDEX "project_version_project_id_commit_hash_key" ON "project_version"("project_id", "commit_hash");

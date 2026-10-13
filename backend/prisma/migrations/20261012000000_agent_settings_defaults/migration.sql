-- Allow catalog agents to exist before a model and credential are assigned.
PRAGMA defer_foreign_keys=ON;
PRAGMA foreign_keys=OFF;
CREATE TABLE "new_agent_settings" (
    "agent_type" TEXT NOT NULL PRIMARY KEY,
    "ai_model_id" INTEGER,
    "ai_credential_id" INTEGER,
    "temperature" DECIMAL,
    "max_tokens" INTEGER,
    CONSTRAINT "agent_settings_ai_model_id_fkey" FOREIGN KEY ("ai_model_id") REFERENCES "ai_model" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "agent_settings_ai_credential_id_fkey" FOREIGN KEY ("ai_credential_id") REFERENCES "ai_credential" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);
INSERT INTO "new_agent_settings" ("agent_type", "ai_model_id", "ai_credential_id", "temperature", "max_tokens")
SELECT "agent_type", "ai_model_id", "ai_credential_id", "temperature", "max_tokens" FROM "agent_settings";
DROP TABLE "agent_settings";
ALTER TABLE "new_agent_settings" RENAME TO "agent_settings";
PRAGMA foreign_keys=ON;
PRAGMA defer_foreign_keys=OFF;

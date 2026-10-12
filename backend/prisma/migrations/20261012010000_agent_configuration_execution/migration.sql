ALTER TABLE "ai_model" ADD COLUMN "revision" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "ai_credential" ADD COLUMN "revision" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "agent_settings" ADD COLUMN "verification_fingerprint" TEXT;
ALTER TABLE "agent_settings" ADD COLUMN "verification_checked_at" DATETIME;
ALTER TABLE "agent_settings" ADD COLUMN "verification_error" TEXT;
ALTER TABLE "agent_execution" ADD COLUMN "configuration_snapshot" TEXT;

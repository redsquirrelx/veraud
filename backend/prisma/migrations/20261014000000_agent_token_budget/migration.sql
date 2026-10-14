-- Nullable fields preserve historical executions and existing agent settings.
ALTER TABLE "agent_settings" ADD COLUMN "token_budget" INTEGER CHECK ("token_budget" IS NULL OR "token_budget" BETWEEN 1 AND 2147483647);
ALTER TABLE "agent_settings" ADD COLUMN "token_tolerance_percent" INTEGER CHECK ("token_tolerance_percent" IS NULL OR "token_tolerance_percent" BETWEEN 0 AND 2147483647);

ALTER TABLE "agent_execution" ADD COLUMN "estimated_tokens" INTEGER CHECK ("estimated_tokens" IS NULL OR "estimated_tokens" BETWEEN 0 AND 2147483647);
ALTER TABLE "agent_execution" ADD COLUMN "accounted_tokens" INTEGER CHECK ("accounted_tokens" IS NULL OR "accounted_tokens" BETWEEN 0 AND 2147483647);
ALTER TABLE "agent_execution" ADD COLUMN "interruption_reason" TEXT;

-- Historical incident dates and exception types are unknown; do not backfill them.
ALTER TABLE "agent_execution" ADD COLUMN "error_detail" TEXT;

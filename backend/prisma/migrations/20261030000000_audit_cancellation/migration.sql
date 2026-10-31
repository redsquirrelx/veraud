ALTER TABLE "agent_execution" ADD COLUMN "cancellation_requested_at" DATETIME;
ALTER TABLE "agent_execution" ADD COLUMN "dispatch_started_at" DATETIME;

-- An active historical execution may already have reached agent-server.
-- Never treat it as undispatched after upgrading.
UPDATE "agent_execution" SET "dispatch_started_at" = "created_at"
WHERE "status" IN ('Waiting', 'Running')
  AND "evaluation_id" IN (SELECT "id" FROM "evaluation" WHERE "type" = 'QualityAudit');

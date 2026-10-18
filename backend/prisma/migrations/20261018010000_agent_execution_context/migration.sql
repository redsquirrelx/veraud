-- Context is supplied by agent-server, never inferred from legacy agent names.
ALTER TABLE "agent_settings" ADD COLUMN "quality_attributes" TEXT NOT NULL DEFAULT '[]';
ALTER TABLE "agent_settings" ADD COLUMN "workflow_ids" TEXT NOT NULL DEFAULT '[]';

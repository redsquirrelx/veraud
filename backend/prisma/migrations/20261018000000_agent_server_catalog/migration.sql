-- Existing selections and execution foreign keys survive catalog synchronization.
-- Legacy rows become active only when declared by the agent-server.
ALTER TABLE "agent_settings" ADD COLUMN "catalog_declared" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "agent_settings" ADD COLUMN "catalog_name" TEXT;
ALTER TABLE "agent_settings" ADD COLUMN "catalog_role" TEXT;
ALTER TABLE "agent_settings" ADD COLUMN "requires_model" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "agent_settings" ADD COLUMN "model_configuration_agent_type" TEXT;
ALTER TABLE "agent_settings" ADD COLUMN "execution_modes" TEXT NOT NULL DEFAULT '[]';
ALTER TABLE "agent_settings" ADD COLUMN "availability" TEXT NOT NULL DEFAULT 'not_executed';

CREATE TABLE "agent_hierarchy" (
    "parent_agent_type" TEXT NOT NULL,
    "child_agent_type" TEXT NOT NULL,
    PRIMARY KEY ("parent_agent_type", "child_agent_type"),
    CONSTRAINT "agent_hierarchy_parent_agent_type_fkey" FOREIGN KEY ("parent_agent_type") REFERENCES "agent_settings" ("agent_type") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "agent_hierarchy_child_agent_type_fkey" FOREIGN KEY ("child_agent_type") REFERENCES "agent_settings" ("agent_type") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "agent_hierarchy_no_self_link" CHECK ("parent_agent_type" <> "child_agent_type")
);
CREATE INDEX "agent_hierarchy_child_agent_type_idx" ON "agent_hierarchy"("child_agent_type");

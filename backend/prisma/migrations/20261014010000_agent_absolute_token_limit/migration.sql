-- Preserve already-applied percentage settings as explicit absolute limits.
ALTER TABLE "agent_settings" ADD COLUMN "absolute_token_limit" INTEGER
  CHECK ("absolute_token_limit" IS NULL OR (
    "absolute_token_limit" BETWEEN 1 AND 2147483647
    AND ("token_budget" IS NULL OR "absolute_token_limit" >= "token_budget")
  ));

UPDATE "agent_settings"
SET "absolute_token_limit" = "token_budget" + CAST("token_budget" * 1.0 * "token_tolerance_percent" / 100 AS INTEGER),
    "verification_fingerprint" = NULL,
    "verification_checked_at" = NULL,
    "verification_error" = NULL
WHERE "token_budget" IS NOT NULL AND "token_tolerance_percent" IS NOT NULL;

ALTER TABLE "agent_settings" DROP COLUMN "token_tolerance_percent";

-- Previous execution snapshots already captured the calculated absolute limit.
-- Keep that limit and remove the superseded percentage without altering results.
UPDATE "agent_execution"
SET "configuration_snapshot" = json_remove("configuration_snapshot", '$.tokenTolerancePercent')
WHERE "configuration_snapshot" IS NOT NULL
  AND json_valid("configuration_snapshot")
  AND json_type("configuration_snapshot", '$.tokenTolerancePercent') IS NOT NULL;

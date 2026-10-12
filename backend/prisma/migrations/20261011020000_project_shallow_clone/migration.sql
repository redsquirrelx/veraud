ALTER TABLE "project" ADD COLUMN "shallow_clone" BOOLEAN NOT NULL DEFAULT false;
UPDATE "project" SET "shallow_clone" = NOT "clone_full_repository";
ALTER TABLE "project" DROP COLUMN "clone_full_repository";

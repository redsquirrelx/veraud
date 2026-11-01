CREATE TABLE "execution_event_stream" (
  "id" TEXT NOT NULL PRIMARY KEY,
  "execution_id" INTEGER NOT NULL,
  "run_id" TEXT,
  "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "execution_event_stream_execution_id_fkey" FOREIGN KEY ("execution_id") REFERENCES "agent_execution" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE TABLE "execution_event" (
  "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
  "event_id" TEXT NOT NULL,
  "stream_id" TEXT NOT NULL,
  "sequence" INTEGER NOT NULL,
  "occurred_at" DATETIME NOT NULL,
  "received_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "run_id" TEXT,
  "invocation_id" TEXT,
  "parent_invocation_id" TEXT,
  "agent_id" TEXT,
  "action_id" TEXT NOT NULL,
  "parent_action_id" TEXT,
  "source_id" TEXT,
  "kind" TEXT NOT NULL,
  "name" TEXT,
  "status" TEXT,
  "metadata" TEXT NOT NULL DEFAULT '{}',
  CONSTRAINT "execution_event_stream_id_fkey" FOREIGN KEY ("stream_id") REFERENCES "execution_event_stream" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX "execution_event_stream_execution_id_idx" ON "execution_event_stream"("execution_id");
CREATE UNIQUE INDEX "execution_event_event_id_key" ON "execution_event"("event_id");
CREATE UNIQUE INDEX "execution_event_stream_id_sequence_key" ON "execution_event"("stream_id", "sequence");
CREATE INDEX "execution_event_stream_id_occurred_at_sequence_idx" ON "execution_event"("stream_id", "occurred_at", "sequence");

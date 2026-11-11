import assert from "node:assert/strict"
import { test } from "node:test"
import { Prisma } from "../../generated/prisma/client.js"
import { AgentExecutionRepository } from "./agent-execution.repository.js"

function serializationError() {
  return new Prisma.PrismaClientKnownRequestError(
    "Could not serialize access due to read/write dependencies among transactions",
    { code: "P2034", clientVersion: "7.10.0" },
  )
}

const receipt = {
  agent_id: "maintainability_manager",
  invocation_id: "i-1",
  run_id: "run-1",
  parent_invocation_id: null,
  status: "running",
  started_at: new Date().toISOString(),
  finished_at: null,
  input_tokens: 100,
  output_tokens: 40,
  phase: null,
  phase_sequence: 1,
  error: null,
  error_detail: null,
}

function harness(options: { serializationFailures?: number, otherError?: boolean } = {}) {
  let attempts = 0
  const row = {
    id: 7, evaluationId: 3, agentType: "maintainability_manager", status: "Running",
    result: JSON.stringify({ run_id: "run-1" }), error: null,
    inputTokens: 10, outputTokens: 5, estimatedTokens: 0, interruptionReason: null,
    createdAt: new Date(), startedAt: new Date(), finishedAt: null,
    cancellationRequestedAt: null, dispatchStartedAt: null,
    configurationSnapshot: JSON.stringify({}), invocationReceipts: "[]",
    evaluation: { id: 3, type: "QualityAudit" },
  }
  const transactions: Array<{ isolationLevel?: string, maxWait?: number, timeout?: number } | undefined> = []
  const db = {
    $transaction: async (fn: (tx: unknown) => Promise<unknown>, txOptions?: { isolationLevel?: string, maxWait?: number, timeout?: number }) => {
      attempts += 1
      transactions.push(txOptions)
      if (options.otherError) {
        throw new Prisma.PrismaClientKnownRequestError("Unique constraint failed", { code: "P2002", clientVersion: "7.10.0" })
      }
      if (options.serializationFailures !== undefined && attempts <= options.serializationFailures) {
        throw serializationError()
      }
      const tx = {
        agentExecution: {
          findUniqueOrThrow: async () => ({ ...row, invocationReceipts: row.invocationReceipts, evaluation: row.evaluation }),
          update: async ({ data }: { where: { id: number }, data: { invocationReceipts: string } }) => {
            row.invocationReceipts = data.invocationReceipts
            return { ...row, invocationReceipts: data.invocationReceipts }
          },
        },
      }
      return fn(tx)
    },
  }
  const repository = new AgentExecutionRepository(db as never, {} as never)
  return { repository, transactions, attempts: () => attempts }
}

test("recordInvocation uses a serializable transaction and retries serialization failures", async () => {
  const { repository, transactions, attempts } = harness({ serializationFailures: 2 })
  const stored = await repository.recordInvocation(7, { ...receipt } as never)
  assert.equal(attempts(), 3)
  assert.deepEqual(transactions.map((item) => item?.isolationLevel), ["Serializable", "Serializable", "Serializable"])
  assert.deepEqual(stored.invocations.map((item) => item.invocation_id), ["i-1"])
})

test("recordInvocation gives up after repeated serialization failures", async () => {
  const { repository, attempts } = harness({ serializationFailures: 10 })
  await assert.rejects(() => repository.recordInvocation(7, { ...receipt } as never), (error: unknown) => {
    assert.ok(error instanceof Prisma.PrismaClientKnownRequestError)
    assert.equal(error.code, "P2034")
    return true
  })
  assert.equal(attempts(), 5)
})

test("recordInvocation does not retry non-serialization errors", async () => {
  const { repository, attempts } = harness({ otherError: true })
  await assert.rejects(() => repository.recordInvocation(7, { ...receipt } as never), (error: unknown) => {
    assert.ok(error instanceof Prisma.PrismaClientKnownRequestError)
    assert.equal(error.code, "P2002")
    return true
  })
  assert.equal(attempts(), 1)
})

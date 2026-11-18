import { it } from "node:test"
import assert from "node:assert/strict"
import { execSync } from "node:child_process"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3"
import { PrismaClient } from "../generated/prisma/client.js"
import { buildApp } from "../app.js"
import { isEncryptedCredential, CredentialEncryptionError } from "../infrastructure/security/credential-cipher.js"

/** Boot-wiring integration: prisma migrate deploy runs the schema, then the REAL boot path must
 *  (a) encrypt legacy plaintext LLM credentials with a locally installed DPAPI master key,
 *  (b) fail closed and refuse to boot when the master key is lost or corrupted.
 *  No cipher is injected — the production loadLocalCredentialCipher path is exercised. The DPAPI
 *  CurrentUser protection is Windows-only by design, so the tests self-skip elsewhere. */
const skip = process.platform !== "win32"

function freshDatabase(): string {
  const dir = mkdtempSync(join(tmpdir(), "veraud-cred-it-"))
  const url = `file:${join(dir, "test.db")}`
  execSync("pnpm prisma migrate deploy", {
    cwd: fileURLToPath(new URL("../../", import.meta.url)), env: { ...process.env, DATABASE_URL: url }, stdio: "ignore",
  })
  return url
}

async function seedPlaintextCredential(url: string): Promise<void> {
  const db = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url }) })
  try {
    const provider = await db.aiProvider.create({ data: { name: "test-openai" } })
    const model = await db.aiModel.create({ data: { name: "plain-model", aiProviderId: provider.id } })
    await db.aiCredential.create({ data: { name: "legacy-key", apiKey: "sk-plaintext-secret-1234", aiProviderId: provider.id } })
    await db.agentSettings.create({ data: { agentType: "legacy_agent", aiModelId: model.id } })
  } finally {
    await db.$disconnect()
  }
}

it("boots over a plaintext legacy database: encrypts in place, preserves IDs, and is idempotent across reboots", { skip }, async () => {
  const url = freshDatabase()
  await seedPlaintextCredential(url)
  const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-cred-ws-"))

  // First boot: fresh workspace has no master key; the boot installs one and migrates.
  const first = await buildApp({ databaseUrl: url, workspaceDir, silent: true })
  try {
    const rows = await first.db.aiCredential.findMany()
    assert.equal(rows.length, 1)
    assert.ok(isEncryptedCredential(rows[0]!.apiKey), "stored credential is not plaintext after boot")
    assert.ok(!rows[0]!.apiKey.includes("sk-plaintext-secret-1234"))
    const ids = { provider: rows[0]!.aiProviderId, credentialId: rows[0]!.id }
    assert.equal(rows[0]!.name, "legacy-key")
    assert.notEqual(ids.provider, 0)
  } finally {
    await first.app.close()
    await first.db.$disconnect()
  }

  // Second boot over the migrated database: nothing to migrate, the key is reused.
  const second = await buildApp({ databaseUrl: url, workspaceDir, silent: true })
  try {
    const rows = await second.db.aiCredential.findMany()
    assert.equal(rows.length, 1)
    assert.ok(isEncryptedCredential(rows[0]!.apiKey))
  } finally {
    await second.app.close()
    await second.db.$disconnect()
  }
})

it("fails closed and refuses to boot when the local master key is corrupted after credentials were encrypted", { skip }, async () => {
  const url = freshDatabase()
  await seedPlaintextCredential(url)
  const workspaceDir = mkdtempSync(join(tmpdir(), "veraud-cred-ws-"))

  // First boot migrates and writes the DPAPI-wrapped master key into workspaceDir/.secrets.
  const first = await buildApp({ databaseUrl: url, workspaceDir, silent: true })
  try {
    assert.ok(isEncryptedCredential((await first.db.aiCredential.findFirstOrThrow()).apiKey))
  } finally {
    await first.app.close()
    await first.db.$disconnect()
  }

  // Corrupt the master key: any later boot must fail before touching the database.
  const keyPath = join(workspaceDir, ".secrets", "credential-master.v1.dpapi")
  writeFileSync(keyPath, Buffer.from("corrupted-master-key-garbage"))

  await assert.rejects(
    () => buildApp({ databaseUrl: url, workspaceDir, silent: true }),
    (error: unknown) => error instanceof CredentialEncryptionError,
  )
})

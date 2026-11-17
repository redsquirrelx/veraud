import assert from "node:assert/strict"
import { test } from "node:test"
import { randomBytes } from "node:crypto"
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { execFileSync } from "node:child_process"
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3"
import { PrismaClient } from "../../generated/prisma/client.js"
import { buildApp } from "../../app.js"
import { makeTestAgentCatalogSource } from "../../tests/helpers/agentCatalog.js"
import { CredentialCipher, CredentialEncryptionError, credentialPreview } from "./credential-cipher.js"
import { loadLocalCredentialCipher } from "./local-credential-key.js"
import { migrateCredentials } from "./credential-migration.js"

test("AES-GCM authenticates identity, ciphertext, preview and master key without disclosing secrets", () => {
  const cipher = new CredentialCipher(randomBytes(32))
  const row = { id: 7, aiProviderId: 3 }
  const secret = "private-llm-token-1234"
  const first = cipher.encrypt(secret, row)
  assert.notEqual(first, cipher.encrypt(secret, row), "each write uses a fresh nonce")
  assert.equal(cipher.decrypt(first, row), secret)
  assert.equal(credentialPreview(first), "****1234")
  assert.ok(!first.includes(secret))
  const encoded = JSON.parse(Buffer.from(first.split(":")[2]!, "base64url").toString())
  for (const change of [{ suffix: "5678" }, { data: Buffer.from("tampered").toString("base64") }]) {
    const broken = "veraud-secret:v1:" + Buffer.from(JSON.stringify({ ...encoded, ...change })).toString("base64url")
    assert.throws(() => cipher.decrypt(broken, row), CredentialEncryptionError)
  }
  assert.throws(() => cipher.decrypt(first, { ...row, id: 8 }), CredentialEncryptionError)
  assert.throws(() => cipher.decrypt(first, { ...row, aiProviderId: 4 }), CredentialEncryptionError)
  assert.throws(() => new CredentialCipher(randomBytes(32)).decrypt(first, row), CredentialEncryptionError)
  for (const broken of ["plaintext", "veraud-secret:v2:bad", "veraud-secret:v1:bad"]) {
    assert.throws(() => cipher.decrypt(broken, row), CredentialEncryptionError)
  }
  assert.equal(credentialPreview(cipher.encrypt("key", row)), "****")
})

test("DPAPI survives restart and refuses to replace a missing/corrupt local master", { skip: process.platform !== "win32" }, () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-dpapi-test-"))
  const first = loadLocalCredentialCipher(directory, false)
  const file = join(directory, "credential-master.v1.dpapi")
  const protectedKey = readFileSync(file)
  assert.ok(protectedKey.length > 32)
  const saved = first.encrypt("local-test-key", { id: 1, aiProviderId: 3 })
  assert.equal(loadLocalCredentialCipher(directory, true).decrypt(saved, { id: 1, aiProviderId: 3 }), "local-test-key")
  writeFileSync(file, "corrupt")
  assert.throws(() => loadLocalCredentialCipher(directory, true), CredentialEncryptionError)
  assert.equal(readFileSync(file, "utf8"), "corrupt")
  const missing = join(directory, "missing")
  assert.throws(() => loadLocalCredentialCipher(missing, true), CredentialEncryptionError)
})

test("legacy credential migration is atomic, idempotent, restores access and preserves revisions", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-credential-migration-"))
  const db = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url: `file:${join(directory, "test.db")}` }) })
  try {
    await db.$executeRawUnsafe('CREATE TABLE ai_credential (id INTEGER PRIMARY KEY AUTOINCREMENT, ai_provider_id INTEGER NOT NULL, name TEXT NOT NULL, api_key TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)')
    const row = await db.aiCredential.create({ data: { name: "legacy", aiProviderId: 3, apiKey: "legacy-secret-1234", revision: 4 } })
    const cipher = new CredentialCipher(randomBytes(32))
    assert.equal(await migrateCredentials(db, cipher), 1)
    const saved = await db.aiCredential.findUniqueOrThrow({ where: { id: row.id } })
    assert.equal(saved.revision, 4)
    assert.equal(saved.name, row.name)
    assert.equal(cipher.decrypt(saved.apiKey, saved), row.apiKey)
    assert.ok(!saved.apiKey.includes(row.apiKey))
    assert.equal(await migrateCredentials(db, cipher), 0)
    const another = await db.aiCredential.create({ data: { name: "unmigrated", aiProviderId: 3, apiKey: "another-secret" } })
    await assert.rejects(migrateCredentials(db, new CredentialCipher(randomBytes(32))), CredentialEncryptionError)
    assert.equal((await db.aiCredential.findUniqueOrThrow({ where: { id: another.id } })).apiKey, "another-secret", "no partial migration on invalid master")
  } finally { await db.$disconnect() }
})

test("application migrates on startup, keeps API previews and unlocks replaced keys after restart", async () => {
  const directory = mkdtempSync(join(tmpdir(), "veraud-encrypted-access-"))
  const databaseUrl = `file:${join(directory, "test.db")}`
  execFileSync(process.execPath, ["node_modules/prisma/build/index.js", "migrate", "deploy"], {
    env: { ...process.env, DATABASE_URL: databaseUrl }, stdio: "ignore",
  })
  const seed = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url: databaseUrl }) })
  const provider = await seed.aiProvider.create({ data: { name: "OpenAI" } })
  const model = await seed.aiModel.create({ data: { name: "test-model", aiProviderId: provider.id } })
  const old = await seed.aiCredential.create({ data: { name: "legacy", apiKey: "test-legacy-1111", aiProviderId: provider.id } })
  await seed.$disconnect()
  const verified: string[] = []
  const options = { databaseUrl, workspaceDir: join(directory, "workspace"), silent: true,
    makeAgentCatalogSource: makeTestAgentCatalogSource,
    makeModelAccessVerifier: () => ({ verify: async (config: { api_key: string }) => { verified.push(config.api_key) } }),
  }
  let { app, db } = await buildApp(options)
  try {
    assert.match((await db.aiCredential.findUniqueOrThrow({ where: { id: old.id } })).apiKey, /^veraud-secret:v1:/)
    const created = await app.inject({ method: "POST", url: `/api/ai-providers/${provider.id}/credentials`, payload: { name: "fresh", apiKey: "new-secret-2222" } })
    assert.equal(created.statusCode, 201)
    const id = created.json().id as number
    assert.equal(created.json().apiKeyPreview, "****2222")
    assert.match((await db.aiCredential.findUniqueOrThrow({ where: { id } })).apiKey, /^veraud-secret:v1:/)
    const assign = await app.inject({ method: "PUT", url: "/api/agent-settings/security", payload: { modelId: model.id, credentialId: old.id } })
    assert.equal(assign.statusCode, 200)
    assert.equal((await app.inject({ method: "POST", url: "/api/agent-settings/security/verify" })).statusCode, 200)
    assert.equal(verified.at(-1), "test-legacy-1111")
    const replaced = await app.inject({ method: "PATCH", url: `/api/ai-providers/${provider.id}/credentials/${old.id}`, payload: { name: "legacy", apiKey: "replacement-3333" } })
    assert.equal(replaced.statusCode, 200)
    assert.equal(replaced.json().apiKeyPreview, "****3333")
    const sealed = (await db.aiCredential.findUniqueOrThrow({ where: { id: old.id } })).apiKey
    await app.inject({ method: "PATCH", url: `/api/ai-providers/${provider.id}/credentials/${old.id}`, payload: { name: "renamed" } })
    assert.equal((await db.aiCredential.findUniqueOrThrow({ where: { id: old.id } })).apiKey, sealed)
    const listed = await app.inject({ url: "/api/agent-settings" })
    assert.equal(listed.json().find((row: { agentType: string }) => row.agentType === "security").verification.status, "not_verified")
    await app.close()
    await db.$disconnect()
    ;({ app, db } = await buildApp(options))
    assert.equal((await db.aiCredential.findUniqueOrThrow({ where: { id: old.id } })).apiKey, sealed, "restart must not rewrite ciphertext")
    assert.equal((await app.inject({ method: "POST", url: "/api/agent-settings/security/verify" })).statusCode, 200)
    assert.equal(verified.at(-1), "replacement-3333")
    const response = await app.inject({ url: "/api/ai-providers" })
    assert.doesNotMatch(response.body, /test-legacy-1111|replacement-3333|new-secret-2222|veraud-secret/)
    assert.ok(response.body.includes("****3333"))
  } finally { await app.close(); await db.$disconnect() }
})

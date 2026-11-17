/** Read-only maintenance verification; never prints keys or ciphertext. */
import { createReadStream } from "node:fs"
import { resolve } from "node:path"
import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3"
import { PrismaClient } from "../../generated/prisma/client.js"
import { isEncryptedCredential } from "./credential-cipher.js"
import { loadLocalCredentialCipher } from "./local-credential-key.js"

async function main() {
  const [databaseUrl, keyDirectory, scan] = process.argv.slice(2)
  if (!databaseUrl?.startsWith("file:") || !keyDirectory || (scan !== undefined && scan !== "--scan")) {
    throw new Error("Usage: verify-local-credentials file:PATH KEY_DIRECTORY [--scan]")
  }
  const db = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url: databaseUrl }) })
  const secrets: Buffer[] = []
  try {
    const cipher = loadLocalCredentialCipher(resolve(keyDirectory), true)
    const rows = await db.aiCredential.findMany()
    for (const row of rows) {
      if (!isEncryptedCredential(row.apiKey)) throw new Error("Legacy plaintext credentials remain")
      secrets.push(Buffer.from(cipher.decrypt(row.apiKey, row)))
    }
    if (scan === "--scan") {
      const overlap = Math.max(1, ...secrets.map((secret) => secret.length)) - 1
      let tail: Buffer = Buffer.alloc(0)
      for await (const bytes of createReadStream(resolve(databaseUrl.slice(5)), { highWaterMark: 1024 * 1024 })) {
        const chunk = Buffer.concat([tail, bytes as Buffer])
        if (secrets.some((secret) => secret.length && chunk.includes(secret))) throw new Error("A full plaintext credential remains in the SQLite file")
        tail = Buffer.from(chunk.subarray(Math.max(0, chunk.length - overlap)))
      }
    }
    console.log(JSON.stringify({ credentials: rows.length, encrypted: true, decryptVerified: true, sqlitePlaintextScan: scan === "--scan" ? "passed" : "not_run" }))
  } finally {
    for (const secret of secrets) secret.fill(0)
    await db.$disconnect()
  }
}

main().catch(() => {
  console.error("Credential verification failed. Check the database and original local DPAPI key; no credentials were changed.")
  process.exitCode = 1
})

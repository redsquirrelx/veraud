import type { PrismaClient } from "../../generated/prisma/client.js"
import { CredentialCipher, isEncryptedCredential } from "./credential-cipher.js"

/** All-or-nothing, idempotent data migration; schema/IDs/revisions stay intact. */
export async function migrateCredentials(db: PrismaClient, cipher: CredentialCipher): Promise<number> {
  // Scrub deleted cell content on this connection as plaintext is replaced.
  await db.$queryRawUnsafe("PRAGMA secure_delete = ON")
  return db.$transaction(async (tx) => {
    const rows = await tx.aiCredential.findMany()
    const pending = []
    for (const row of rows) {
      if (isEncryptedCredential(row.apiKey)) {
        cipher.decrypt(row.apiKey, row) // Abort on lost key, corruption or wrong account.
      } else {
        const encrypted = cipher.encrypt(row.apiKey, row)
        if (cipher.decrypt(encrypted, row) !== row.apiKey) throw new Error("Credential migration verification failed")
        pending.push({ ...row, apiKey: encrypted })
      }
    }
    if (!pending.length) return 0
    for (const row of pending) await tx.aiCredential.update({ where: { id: row.id }, data: { apiKey: row.apiKey } })
    return pending.length
  })
}

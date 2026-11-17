# Local LLM credential encryption (Windows)

Provider credentials saved through Settings are encrypted **before** storage in
SQLite, using Node's AES-256-GCM. No external service, new package or network is
required. Frontend contracts and credential IDs/assignments stay unchanged.

## Master key and recovery

`appdata/workspace/.secrets/credential-master.v1.dpapi` contains a random 256-bit
master key protected with Windows DPAPI **CurrentUser**. The backend unwraps it
under the Windows account that initialized it. The key is never in SQLite, argv,
`.env`, HTTP responses or execution snapshots.

Keep this file together with database backups, privately. It is **not a portable
export**: copying the DPAPI blob to another Windows account/machine is not a
recovery strategy. Restore under the original Windows profile/DPAPI context, or
re-enter the provider credentials on a new installation. Losing the master key
does not destroy projects/reports, but makes stored provider keys unreadable.
Never delete the master to “reset” an existing encrypted database: startup refuses
to replace a missing/invalid key. Do not commit `.secrets` or appdata to Git.

## Storage and use

The existing `ai_credential.api_key` column holds a versioned envelope with key ID,
random 12-byte nonce, 16-byte authentication tag, ciphertext and public last-four
preview. The envelope authenticates the credential ID, provider ID, version and
preview. Swapped/tampered rows or an incorrect key fail closed. Metadata/listing
does not decrypt credentials; decryption is done when preparing model access.
The provider still needs the clear key in process memory/transport during use.

## Migration

On startup the backend validates existing ciphertext and migrates legacy rows in
one transaction. IDs, names, revisions, assignments and verification fingerprints
are preserved. No recovery or plaintext backup is created; failed migration rolls
back all credential rows. Rerunning the migration is safe and does not re-encrypt
migrated rows. Legacy imports encountered during execution preparation are
encrypted before use.
New API writes never send plaintext keys to SQLite, even temporarily.

SQLite `secure_delete` is enabled on the application connection for replaced
cells. Existing external backups, filesystem snapshots, deleted journals, SSD
history and keys previously written to logs are **not** retroactively sanitized.
Rotate provider keys if prior disclosure is suspected. Do not claim forensic
erasure from an application-level migration.

Read-only verification (from `backend/`, prints only counts/status):

```powershell
pnpm exec tsx src/infrastructure/security/verify-local-credentials.ts `
  file:../appdata/database.db ../appdata/workspace/.secrets --scan
```

`--scan` checks the SQLite file for full current plaintext credentials; it does
not inspect other files/backups. No model calls are made.

## Limits

- Windows-only default key storage. Tests/other hosts can inject a trusted cipher
  at application composition; there is no insecure OS fallback.
- This protects copied databases, not malware running as the same Windows user.
- Existing backend → agent-server transport/authentication is unchanged.
- Standalone runner `LLM_API_KEY` in `.env` is unchanged (separate dev workflow).
- Envelope version/key ID allow detecting incompatible keys; a general key
  rotation/export UI is not implemented. Replacing an individual API key through
  Settings remains supported and invalidates its existing access verification.

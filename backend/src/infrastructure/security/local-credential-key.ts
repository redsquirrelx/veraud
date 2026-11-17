import { spawnSync } from "node:child_process"
import { randomBytes, randomUUID } from "node:crypto"
import { existsSync, linkSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { CredentialCipher, CredentialEncryptionError } from "./credential-cipher.js"

/** DPAPI CurrentUser: no service/network, no key in argv, env, logs or SQLite. */
function dpapi(value: Buffer, protect: boolean): Buffer {
  if (process.platform !== "win32") throw new CredentialEncryptionError()
  const operation = protect ? "Protect" : "Unprotect"
  const script = `$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Security; `
    + `$b=[Convert]::FromBase64String([Console]::In.ReadToEnd()); `
    + `$r=[Security.Cryptography.ProtectedData]::${operation}($b,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser); `
    + `[Console]::Out.Write([Convert]::ToBase64String($r))`
  const result = spawnSync("powershell.exe", ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script], {
    input: value.toString("base64"), encoding: "utf8", windowsHide: true, timeout: 15000, maxBuffer: 16384,
  })
  if (result.error || result.status !== 0 || !result.stdout.trim()) throw new CredentialEncryptionError()
  return Buffer.from(result.stdout.trim(), "base64")
}

export function loadLocalCredentialCipher(directory: string, requireExisting: boolean): CredentialCipher {
  const path = join(directory, "credential-master.v1.dpapi")
  if (!existsSync(path)) {
    if (requireExisting) throw new CredentialEncryptionError() // Never replace a lost key.
    mkdirSync(directory, { recursive: true, mode: 0o700 })
    const master = randomBytes(32)
    let protectedKey: Buffer
    try { protectedKey = dpapi(master, true) } finally { master.fill(0) }
    const temporary = join(directory, `${randomUUID()}.tmp`)
    try {
      writeFileSync(temporary, protectedKey, { flag: "wx", mode: 0o600 })
      try { linkSync(temporary, path) } catch (error) {
        // Atomic installation; a concurrent initializer may have won.
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw new CredentialEncryptionError()
      }
    } finally { if (existsSync(temporary)) unlinkSync(temporary) }
  }
  let key: Buffer
  try { key = dpapi(readFileSync(path), false) } catch { throw new CredentialEncryptionError() }
  try { return new CredentialCipher(key) } finally { key.fill(0) }
}

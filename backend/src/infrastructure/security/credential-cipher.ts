import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto"

const PREFIX = "veraud-secret:"
const VERSION = "v1"
type Identity = { id: number, aiProviderId: number }
type Envelope = { kid: string, iv: string, tag: string, data: string, suffix: string }

export class CredentialEncryptionError extends Error {
  constructor() {
    super("Local credential encryption is unavailable or the encrypted credential is invalid. Restore the original local key or replace the credential.")
    this.name = "CredentialEncryptionError"
  }
}

export function isEncryptedCredential(value: string): boolean { return value.startsWith(PREFIX) }

function parse(value: string): Envelope {
  try {
    const parts = value.split(":")
    if (parts.length !== 3 || parts[1] !== VERSION) throw new Error()
    const e = JSON.parse(Buffer.from(parts[2]!, "base64url").toString("utf8")) as Envelope
    if (!e || ![e.kid, e.iv, e.tag, e.data, e.suffix].every((v) => typeof v === "string")) throw new Error()
    if (!/^[a-f0-9]{16}$/.test(e.kid) || Buffer.from(e.iv, "base64").length !== 12
      || Buffer.from(e.tag, "base64").length !== 16 || e.suffix.length > 4) throw new Error()
    return e
  } catch { throw new CredentialEncryptionError() }
}

/** Public preview only; listing credentials never needs the master key/plaintext. */
export function credentialPreview(value: string): string {
  const suffix = isEncryptedCredential(value) ? parse(value).suffix : value.length > 4 ? value.slice(-4) : ""
  return `****${suffix}`
}

export class CredentialCipher {
  private readonly key: Buffer
  readonly keyId: string

  constructor(key: Buffer) {
    if (key.length !== 32) throw new CredentialEncryptionError()
    this.key = Buffer.from(key)
    this.keyId = createHash("sha256").update(key).digest("hex").slice(0, 16)
  }

  private aad(identity: Identity, suffix: string): Buffer {
    // Prevent swapping encrypted keys across rows/providers or editing previews.
    return Buffer.from(JSON.stringify([VERSION, this.keyId, identity.id, identity.aiProviderId, suffix]))
  }

  encrypt(value: string, identity: Identity): string {
    const iv = randomBytes(12)
    const suffix = value.length > 4 ? value.slice(-4) : ""
    const cipher = createCipheriv("aes-256-gcm", this.key, iv)
    cipher.setAAD(this.aad(identity, suffix))
    const data = Buffer.concat([cipher.update(value, "utf8"), cipher.final()])
    const envelope: Envelope = { kid: this.keyId, iv: iv.toString("base64"), tag: cipher.getAuthTag().toString("base64"),
      data: data.toString("base64"), suffix }
    return `${PREFIX}${VERSION}:${Buffer.from(JSON.stringify(envelope)).toString("base64url")}`
  }

  decrypt(value: string, identity: Identity): string {
    try {
      const e = parse(value)
      if (e.kid !== this.keyId) throw new Error()
      const cipher = createDecipheriv("aes-256-gcm", this.key, Buffer.from(e.iv, "base64"))
      cipher.setAAD(this.aad(identity, e.suffix))
      cipher.setAuthTag(Buffer.from(e.tag, "base64"))
      return Buffer.concat([cipher.update(Buffer.from(e.data, "base64")), cipher.final()]).toString("utf8")
    } catch { throw new CredentialEncryptionError() }
  }
}

// Repositories constructed with the same Prisma client share the trusted cipher.
const ciphers = new WeakMap<object, CredentialCipher>()
export function configureCredentialCipher(db: object, cipher: CredentialCipher): void { ciphers.set(db, cipher) }
export function credentialCipherFor(db: object): CredentialCipher {
  const cipher = ciphers.get(db)
  if (!cipher) throw new CredentialEncryptionError()
  return cipher
}

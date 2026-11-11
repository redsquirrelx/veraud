// CORS compares the browser's Origin header against these values exactly, so
// configured hosts are reduced to a canonical scheme://host:port form.
const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"])

function hostnameOf(value: string): string {
  const withoutPath = value.split(/[/?#]/, 1)[0] ?? ""
  const host = withoutPath.startsWith("[")
    ? withoutPath.slice(0, withoutPath.indexOf("]") + 1)
    : withoutPath.split(":")[0] ?? ""
  return host.replace(/^\[|\]$/g, "").toLowerCase()
}

function normalizeCorsOrigin(value: string): string | null {
  const trimmed = value.trim()
  if (trimmed === "") return null

  const hasScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)
  const candidate = hasScheme
    ? trimmed
    : `${LOCAL_HOSTNAMES.has(hostnameOf(trimmed)) ? "http" : "https"}://${trimmed}`

  try {
    return new URL(candidate).origin
  } catch {
    return null
  }
}

/** Accepts one or more comma-separated origins and returns their canonical
 *  origins, ignoring blanks, duplicates and entries that are not URLs. */
export function normalizeCorsOrigins(values: readonly string[]): string[] {
  const origins = new Set<string>()
  for (const value of values) {
    for (const part of value.split(",")) {
      const origin = normalizeCorsOrigin(part)
      if (origin !== null) origins.add(origin)
    }
  }
  return [...origins]
}

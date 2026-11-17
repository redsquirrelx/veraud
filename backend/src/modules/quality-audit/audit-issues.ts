import { createReadStream } from "node:fs"

/** Select one small top-level value without parsing/materializing the evidence
 * inventory (which can be hundreds of MB). JSON strings and nested containers
 * are tracked across chunks; only the requested value is retained in memory. */
export async function readAuditIssues(path: string): Promise<unknown[]> {
  const stream = createReadStream(path, { encoding: "utf8", highWaterMark: 64 * 1024 })
  let depth = 0
  let inString = false
  let escaped = false
  let key = ""
  let readingKey = false
  let expectingKey = false
  let selected = false
  let capturing = false
  let value = ""
  try {
    for await (const chunk of stream) {
      for (const char of String(chunk)) {
        if (capturing && !inString && depth === 1 && (char === "," || char === "}")) {
          const result: unknown = JSON.parse(value)
          return Array.isArray(result) ? result : []
        }
        if (capturing) {
          value += char
          if (value.length > 1_048_576) throw new Error("Audit incident detail exceeds the supported size")
        }
        if (inString) {
          if (readingKey) key += char
          if (escaped) escaped = false
          else if (char === "\\") escaped = true
          else if (char === '"') {
            inString = false
            if (readingKey) {
              selected = JSON.parse(key) === "execution_issues"
              readingKey = false
              expectingKey = false
            }
          }
          continue
        }
        if (char === '"') {
          inString = true
          if (depth === 1 && expectingKey) { readingKey = true; key = '"' }
        } else if (char === "{" || char === "[") {
          depth++
          if (depth === 1 && char === "{") expectingKey = true
        } else if (char === "}" || char === "]") depth--
        else if (depth === 1 && char === ",") { expectingKey = true; selected = false }
        else if (depth === 1 && char === ":" && selected) capturing = true
      }
    }
    if (depth !== 0 || inString) throw new Error("Incomplete audit annexes")
    return []
  } finally {
    stream.destroy()
  }
}

/** Explicit projection: never return evidence, nested reports or arbitrary
 * properties from a producer's issue record. */
export function projectAuditIssues(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return []
  const text = (item: unknown) => typeof item === "string" ? item.slice(0, 16_384) : null
  const strings = (item: unknown) => Array.isArray(item)
    ? item.filter((entry): entry is string => typeof entry === "string").slice(0, 100).map((entry) => entry.slice(0, 16_384)) : []
  return value.slice(0, 100).flatMap((item: unknown) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return []
    const issue = item as Record<string, unknown>
    return [{ agent_id: text(issue.agent_id), invocation_id: text(issue.invocation_id),
      status: text(issue.status), termination_reason: text(issue.termination_reason),
      explanation: text(issue.explanation), incidents: strings(issue.incidents), diagnostics: strings(issue.diagnostics) }]
  })
}

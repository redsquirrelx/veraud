export const branchInput = {
  type: "string",
  description: "Trimmed branch name, 1ΓÇô255 characters: letters, numbers, dot, underscore, slash or dash. No .., --, leading dash/slash/dot or Git-special sequences. Validated by the service.",
  examples: ["main"],
} as const

export const commitHashInput = {
  type: "string",
  description: "7ΓÇô40 hexadecimal characters, case insensitive; trimmed and returned lowercase.",
  examples: ["aaaaaaa"],
} as const

export function objectResponse(properties: Record<string, unknown>) {
  return { type: "object", required: Object.keys(properties), properties }
}

/** Domain errors and framework validation have distinct public shapes. */
export function errorResponses<const Codes extends readonly number[]>(codes: Codes, domain = "MessageError", mixed400 = true): Record<Codes[number], unknown> {
  return Object.fromEntries(codes.map((code) => [code,
    code === 400
      ? mixed400
        ? { anyOf: [{ $ref: "ValidationError#" }, { $ref: `${domain}#` }] }
        : { $ref: "ValidationError#" }
      : { $ref: `${domain}#` },
  ])) as Record<Codes[number], unknown>
}

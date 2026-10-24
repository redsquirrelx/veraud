/** Controlled messages only; provider payloads must never be persisted or displayed. */
export const modelAccessErrors = {
  access_denied: "Provider rejected the credential or its permissions",
  invalid_configuration: "Invalid verification configuration; check provider, model and credential",
  model_not_found: "Model not found or unavailable for this credential",
  rate_limited: "Provider rate limit or quota exceeded; access was not confirmed",
  provider_unavailable: "Provider temporarily unavailable; access was not confirmed. Try again later",
  timeout: "Model access verification timed out; access was not confirmed",
  verification_failed: "Model access verification could not be completed; access was not confirmed",
  agent_server_unavailable: "Agent-server unavailable or timed out; model access was not confirmed",
} as const

export type ModelAccessErrorCode = keyof typeof modelAccessErrors

export class ModelAccessError extends Error {
  constructor(readonly code: ModelAccessErrorCode) { super(modelAccessErrors[code]) }
}

export function storedVerificationFailure(value: string | null): { message: string | null, reason?: ModelAccessErrorCode } {
  if (value?.startsWith("model_access:")) {
    const code = value.slice("model_access:".length)
    if (Object.hasOwn(modelAccessErrors, code)) return {
      message: modelAccessErrors[code as ModelAccessErrorCode], reason: code as ModelAccessErrorCode,
    }
  }
  return { message: value }
}

import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, verifyAgentSettings, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button } from "../../shared/ui-kit/index.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"

const failureKeys: Record<string, ParseKeys<"settings">> = {
  access_denied: "agents.verification.errors.accessDenied",
  invalid_configuration: "agents.verification.errors.invalidConfiguration",
  model_not_found: "agents.verification.errors.modelNotFound",
  rate_limited: "agents.verification.errors.rateLimited",
  provider_unavailable: "agents.verification.errors.providerUnavailable",
  timeout: "agents.verification.errors.timeout",
  verification_failed: "agents.verification.errors.verificationFailed",
  agent_server_unavailable: "agents.verification.errors.agentServerUnavailable",
}

export function AgentAccessVerification({ agent, disabled, onUpdated }: { agent: AgentSettings, disabled: boolean, onUpdated: (agent: AgentSettings) => void }) {
  const { t } = useTranslation("settings")
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState<{ key: ParseKeys<"settings">, detail?: string } | null>(null)
  const verification = disabled ? undefined : agent.verification
  const failureKey = verification?.reason && Object.hasOwn(failureKeys, verification.reason) ? failureKeys[verification.reason] : undefined
  const verificationMessage = failureKey ? t(failureKey) : verification?.message
  async function verify() {
    if (verifying || disabled || !agent.configured) return
    setVerifying(true)
    setError(null)
    try { onUpdated(await verifyAgentSettings(agent.agentType)) }
    catch (failure) {
      setError(failure instanceof ApiError
        ? { key: "agents.verification.verifyFailedWithDetail", detail: failure.message }
        : { key: "agents.verification.verifyFailed" })
    }
    finally { setVerifying(false) }
  }
  const statusKey = verification?.status === "verified"
    ? "agents.verification.verified"
    : verification?.status === "failed"
      ? "agents.verification.needsAttention"
      : "agents.verification.notVerified"
  return <div className="settings-agent-verification">
    <div className="settings-agent-options-heading">
      <Badge tone={verification?.status === "verified" ? "success" : verification?.status === "failed" ? "warning" : "info"}>
        {t(statusKey)}
      </Badge>
      <Button variant="secondary" disabled={disabled || !agent.configured || verifying} loading={verifying} loadingText={t("agents.verification.verifying")} onClick={() => void verify()}>{t("agents.verification.verify")}</Button>
    </div>
    {verification?.checkedAt && <p className="settings-hint">{t("agents.verification.lastChecked", { date: formatDateTime(verification.checkedAt) })}</p>}
    {(error || verificationMessage) && <p className="settings-error" role="alert">{error ? error.detail === undefined ? t(error.key) : t(error.key, { detail: error.detail }) : verificationMessage}</p>}
    <p className="settings-hint">{t("agents.verification.hint")}</p>
    {disabled && <p className="settings-hint">{t("agents.verification.saveFirst")}</p>}
  </div>
}

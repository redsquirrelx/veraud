import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, verifyAgentSettings, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button } from "../../shared/ui-kit/index.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"

export function AgentAccessVerification({ agent, disabled, onUpdated }: { agent: AgentSettings, disabled: boolean, onUpdated: (agent: AgentSettings) => void }) {
  const { t } = useTranslation("settings")
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState<{ key: ParseKeys<"settings">, detail?: string } | null>(null)
  const verification = agent.verification
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
    {(error || verification?.message) && <p className="settings-error" role="alert">{error ? error.detail === undefined ? t(error.key) : t(error.key, { detail: error.detail }) : verification?.message}</p>}
    <p className="settings-hint">{t("agents.verification.hint")}</p>
    {disabled && <p className="settings-hint">{t("agents.verification.saveFirst")}</p>}
  </div>
}

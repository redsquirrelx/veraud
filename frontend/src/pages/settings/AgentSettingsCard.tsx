import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, saveAgentSettings, type AgentSettings, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Card, ItemSelector } from "../../shared/ui-kit/index.ts"
import { AgentAccessVerification } from "./AgentAccessVerification.tsx"
import { DEFAULT_TOKEN_BUDGET, DEFAULT_ABSOLUTE_TOKEN_LIMIT } from "../../shared/agent-monitor/tokenBudgets.ts"
import { formatNumber } from "../../shared/i18n/format.ts"

interface AgentSettingsCardProps {
  agent: AgentSettings
  providers: AiProviderDetail[]
  providersLoading: boolean
  onSaved: (agent: AgentSettings) => void
  onConfigure: () => void
  onVerified: (agent: AgentSettings) => void
  label?: string
  modelAccessOnly?: boolean
}

interface AgentSaveError {
  key: ParseKeys<"settings">
  detail?: string
}

export function AgentSettingsCard({ agent, providers, providersLoading, onSaved, onConfigure, onVerified, label, modelAccessOnly = false }: AgentSettingsCardProps) {
  const { t } = useTranslation("settings")
  const [modelId, setModelId] = useState<number | null>(agent.configuration?.model.id ?? null)
  const [credentialId, setCredentialId] = useState<number | null>(agent.configuration?.credential.id ?? null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<AgentSaveError | null>(null)
  const [saved, setSaved] = useState(false)
  const savedModelId = agent.configuration?.model.id ?? null
  const savedCredentialId = agent.configuration?.credential.id ?? null
  const [previousSelection, setPreviousSelection] = useState({ modelId: savedModelId, credentialId: savedCredentialId })
  if (previousSelection.modelId !== savedModelId || previousSelection.credentialId !== savedCredentialId) {
    setPreviousSelection({ modelId: savedModelId, credentialId: savedCredentialId })
    setModelId(savedModelId)
    setCredentialId(savedCredentialId)
  }
  const models = providers.flatMap((provider) => provider.models.map((model) => ({ ...model, providerId: provider.id, providerName: provider.name })))
  const model = models.find((entry) => entry.id === modelId)
  const credentials = providers.find((provider) => provider.id === model?.providerId)?.credentials ?? []
  const dirty = modelId !== (agent.configuration?.model.id ?? null) || credentialId !== (agent.configuration?.credential.id ?? null)
  const canSave = model !== undefined && credentials.some((entry) => entry.id === credentialId) && dirty && !providersLoading && !saving

  function selectModel(id: string) {
    const next = models.find((entry) => entry.id === Number(id))
    if (next?.providerId !== model?.providerId) setCredentialId(null)
    setModelId(Number(id))
    setError(null)
    setSaved(false)
  }

  async function save() {
    if (!canSave || modelId === null || credentialId === null) return
    setSaving(true)
    setError(null)
    try {
      const updated = await saveAgentSettings(agent.agentType, modelId, credentialId)
      setModelId(updated.configuration?.model.id ?? null)
      setCredentialId(updated.configuration?.credential.id ?? null)
      onSaved(updated)
      setSaved(true)
    } catch (failure) {
      setError(failure instanceof ApiError
        ? { key: "agents.saveFailedWithDetail", detail: failure.message }
        : { key: "agents.saveFailed" })
    } finally {
      setSaving(false)
    }
  }

  const statusKey = dirty
    ? "agents.status.unsavedChanges"
    : agent.configured
      ? "agents.status.configured"
      : agent.configuration
        ? "agents.status.needsAttention"
        : "agents.status.notConfigured"

  return (
    <Card>
      <div className="settings-agent-heading">
        <h3>{label ?? agent.agentType}</h3>
        <Badge tone={dirty ? "info" : agent.configured ? "success" : "info"}>
          {t(statusKey)}
        </Badge>
      </div>
      <ItemSelector
        label={t("agents.form.model")}
        items={models.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.providerName }))}
        selectedId={modelId === null ? null : String(modelId)}
        placeholder={t("agents.form.selectModel")}
        emptyText={t("agents.form.noModels")}
        onSelect={selectModel}
        hasMore={false}
        onLoadMore={() => {}}
        loading={providersLoading}
        disabled={saving}
      />
      <ItemSelector
        label={t("agents.form.credential")}
        items={credentials.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.apiKeyPreview }))}
        selectedId={credentialId === null ? null : String(credentialId)}
        placeholder={model ? t("agents.form.selectCredential") : t("agents.form.selectModelFirst")}
        emptyText={t("agents.form.noCredentialsForProvider")}
        onSelect={(id) => { setCredentialId(Number(id)); setError(null); setSaved(false) }}
        hasMore={false}
        onLoadMore={() => {}}
        disabled={!model || providersLoading || saving}
      />
      {error && <p className="settings-error" role="alert">{error.detail === undefined ? t(error.key) : t(error.key, { detail: error.detail })}</p>}
      {saved && !dirty && <p className="settings-hint" role="status">{t("agents.card.saved")}</p>}
      <AgentAccessVerification agent={agent} disabled={dirty || saving || providersLoading} onUpdated={onVerified} />
      {!modelAccessOnly && <p className="settings-hint">{t("agents.card.tokenSummary", { budget: formatNumber(agent.configuration?.tokenBudget ?? DEFAULT_TOKEN_BUDGET), limit: formatNumber(agent.configuration?.absoluteTokenLimit ?? DEFAULT_ABSOLUTE_TOKEN_LIMIT) })}</p>}
      <div className="settings-agent-footer">
        {!modelAccessOnly && <Button variant="secondary" ariaLabel={t("agents.card.configureAgent", { agentType: agent.agentType })} onClick={onConfigure}>{t("agents.card.configure")}</Button>}
        <Button disabled={!canSave} loading={saving} loadingText={t("agents.card.saving")} onClick={() => void save()}>{t("agents.card.saveChanges")}</Button>
      </div>
    </Card>
  )
}

import { useState } from "react"
import { ApiError, saveAgentSettings, type AgentSettings, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Card, ItemSelector } from "../../shared/ui-kit/index.ts"
import { AgentAccessVerification } from "./AgentAccessVerification.tsx"

interface AgentSettingsCardProps {
  agent: AgentSettings
  providers: AiProviderDetail[]
  providersLoading: boolean
  onSaved: (agent: AgentSettings) => void
  onConfigure: () => void
  onVerified: (agent: AgentSettings) => void
}

export function AgentSettingsCard({ agent, providers, providersLoading, onSaved, onConfigure, onVerified }: AgentSettingsCardProps) {
  const [modelId, setModelId] = useState<number | null>(agent.configuration?.model.id ?? null)
  const [credentialId, setCredentialId] = useState<number | null>(agent.configuration?.credential.id ?? null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
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
    setError("")
    setSaved(false)
  }

  async function save() {
    if (!canSave || modelId === null || credentialId === null) return
    setSaving(true)
    setError("")
    try {
      const updated = await saveAgentSettings(agent.agentType, modelId, credentialId)
      setModelId(updated.configuration?.model.id ?? null)
      setCredentialId(updated.configuration?.credential.id ?? null)
      onSaved(updated)
      setSaved(true)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Could not save agent settings")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <div className="settings-agent-heading">
        <h3>{agent.agentType}</h3>
        <Badge tone={dirty ? "info" : agent.configured ? "success" : "info"}>
          {dirty ? "Unsaved changes" : agent.configured ? "Configured" : agent.configuration ? "Needs attention" : "Not configured"}
        </Badge>
      </div>
      <ItemSelector
        label="Model"
        items={models.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.providerName }))}
        selectedId={modelId === null ? null : String(modelId)}
        placeholder="Select a model..."
        emptyText="No models registered"
        onSelect={selectModel}
        hasMore={false}
        onLoadMore={() => {}}
        loading={providersLoading}
        disabled={saving}
      />
      <ItemSelector
        label="Credential"
        items={credentials.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.apiKeyPreview }))}
        selectedId={credentialId === null ? null : String(credentialId)}
        placeholder={model ? "Select a credential..." : "Select a model first"}
        emptyText="No credentials registered for this provider"
        onSelect={(id) => { setCredentialId(Number(id)); setError(""); setSaved(false) }}
        hasMore={false}
        onLoadMore={() => {}}
        disabled={!model || providersLoading || saving}
      />
      {error && <p className="settings-error" role="alert">{error}</p>}
      {saved && !dirty && <p className="settings-hint" role="status">Configuration saved.</p>}
      <AgentAccessVerification agent={agent} disabled={dirty || saving || providersLoading} onUpdated={onVerified} />
      <div className="settings-agent-footer">
        <Button variant="secondary" ariaLabel={`Configure ${agent.agentType}`} onClick={onConfigure}>Configure</Button>
        <Button disabled={!canSave} loading={saving} loadingText="Saving..." onClick={() => void save()}>Save changes</Button>
      </div>
    </Card>
  )
}

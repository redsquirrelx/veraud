import { useState } from "react"
import { ApiError, saveAgentSettings, type AgentSettings, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Drawer, ItemSelector } from "../../shared/ui-kit/index.ts"
import { AgentAccessVerification } from "./AgentAccessVerification.tsx"
import { DEFAULT_TOKEN_BUDGET, DEFAULT_ABSOLUTE_TOKEN_LIMIT } from "../../shared/agent-monitor/tokenBudgets.ts"

interface Props {
  agent: AgentSettings
  open: boolean
  providers: AiProviderDetail[]
  providersLoading: boolean
  providersError: string
  onClose: () => void
  onSaved: (agent: AgentSettings) => void
  onVerified: (agent: AgentSettings) => void
}

export function AgentSettingsDrawer({ agent, open, providers, providersLoading, providersError, onClose, onSaved, onVerified }: Props) {
  const [modelId, setModelId] = useState<number | null>(agent.configuration?.model.id ?? null)
  const [credentialId, setCredentialId] = useState<number | null>(agent.configuration?.credential.id ?? null)
  const [temperature, setTemperature] = useState(String(agent.configuration?.temperature ?? ""))
  const [maxTokens, setMaxTokens] = useState(String(agent.configuration?.maxTokens ?? ""))
  const [tokenBudget, setTokenBudget] = useState(String(agent.configuration?.tokenBudget ?? ""))
  const [absoluteTokenLimit, setAbsoluteTokenLimit] = useState(String(agent.configuration?.absoluteTokenLimit ?? ""))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  const [previous, setPrevious] = useState({ open, agent })
  if (previous.open !== open || previous.agent !== agent) {
    setPrevious({ open, agent })
    if (open) {
      setModelId(agent.configuration?.model.id ?? null)
      setCredentialId(agent.configuration?.credential.id ?? null)
      setTemperature(String(agent.configuration?.temperature ?? ""))
      setMaxTokens(String(agent.configuration?.maxTokens ?? ""))
      setTokenBudget(String(agent.configuration?.tokenBudget ?? ""))
      setAbsoluteTokenLimit(String(agent.configuration?.absoluteTokenLimit ?? ""))
      setError("")
    }
  }

  const models = providers.flatMap((provider) => provider.models.map((model) => ({ ...model, providerId: provider.id, providerName: provider.name })))
  const model = models.find((entry) => entry.id === modelId)
  const credentials = providers.find((provider) => provider.id === model?.providerId)?.credentials ?? []
  const numericTemperature = temperature.trim() === "" ? null : Number(temperature)
  const numericMaxTokens = maxTokens.trim() === "" ? null : Number(maxTokens)
  const numericBudget = tokenBudget.trim() === "" ? null : Number(tokenBudget)
  const numericAbsolute = absoluteTokenLimit.trim() === "" ? null : Number(absoluteTokenLimit)
  const positiveTokens = (value: number | null) => value === null || (Number.isInteger(value) && value >= 1 && value <= 2147483647)
  const budgetValid = positiveTokens(numericBudget)
  const absoluteValid = positiveTokens(numericAbsolute)
  const effectiveBudget = numericBudget ?? DEFAULT_TOKEN_BUDGET
  const effectiveAbsolute = numericAbsolute ?? DEFAULT_ABSOLUTE_TOKEN_LIMIT
  const limitsValid = effectiveAbsolute >= effectiveBudget
  const temperatureValid = numericTemperature === null || (Number.isFinite(numericTemperature) && numericTemperature >= 0 && numericTemperature <= 2)
  const tokensValid = numericMaxTokens === null || (Number.isInteger(numericMaxTokens) && numericMaxTokens >= 1 && numericMaxTokens <= 2147483647)
  const dirty = modelId !== (agent.configuration?.model.id ?? null)
    || credentialId !== (agent.configuration?.credential.id ?? null)
    || numericTemperature !== (agent.configuration?.temperature ?? null)
    || numericMaxTokens !== (agent.configuration?.maxTokens ?? null)
    || numericBudget !== (agent.configuration?.tokenBudget ?? null)
    || numericAbsolute !== (agent.configuration?.absoluteTokenLimit ?? null)
  const canSave = dirty && !!model && credentials.some((credential) => credential.id === credentialId)
    && temperatureValid && tokensValid && budgetValid && absoluteValid && limitsValid && !saving && !providersLoading && !providersError

  async function save() {
    if (!canSave || modelId === null || credentialId === null) return
    setSaving(true)
    setError("")
    try {
      const updated = await saveAgentSettings(agent.agentType, modelId, credentialId, {
        temperature: numericTemperature, maxTokens: numericMaxTokens,
        tokenBudget: numericBudget, absoluteTokenLimit: numericAbsolute,
      })
      onSaved(updated)
      onClose()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "Could not save agent settings")
    } finally {
      setSaving(false)
    }
  }

  return <Drawer
    open={open}
    title={`Configure ${agent.agentType}`}
    description="Choose model access and generation parameters."
    onClose={() => { if (!saving) onClose() }}
    footer={<>
      <Button variant="secondary" disabled={saving} onClick={onClose}>Cancel</Button>
      <Button disabled={!canSave} loading={saving} loadingText="Saving..." onClick={() => void save()}>Save changes</Button>
    </>}
  >
    <form className="settings-agent-editor" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <div className="settings-agent-drawer-summary">
        <span className="settings-agent-drawer-name">{agent.agentType}</span>
        <Badge tone={dirty ? "info" : agent.configured ? "success" : "info"}>{dirty ? "Unsaved changes" : agent.configured ? "Configured" : "Not configured"}</Badge>
      </div>
      {(error || providersError) && <p className="settings-error" role="alert">{error || providersError}</p>}
      <section className="settings-agent-editor-section">
        <h3>Model & access</h3>
        <p className="settings-hint">The model and credential must belong to the same provider.</p>
        <ItemSelector label="Model" items={models.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.providerName }))}
          selectedId={modelId === null ? null : String(modelId)} placeholder="Select a model..." emptyText="No models registered"
          onSelect={(id) => {
            const next = models.find((entry) => entry.id === Number(id))
            if (next?.providerId !== model?.providerId) setCredentialId(null)
            setModelId(Number(id)); setError("")
          }} hasMore={false} onLoadMore={() => {}} loading={providersLoading} disabled={saving || !!providersError} />
        <ItemSelector label="Credential" items={credentials.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.apiKeyPreview }))}
          selectedId={credentialId === null ? null : String(credentialId)} placeholder={model ? "Select a credential..." : "Select a model first"}
          emptyText="No credentials registered for this provider" onSelect={(id) => { setCredentialId(Number(id)); setError("") }}
          hasMore={false} onLoadMore={() => {}} disabled={!model || providersLoading || saving || !!providersError} />
        <AgentAccessVerification agent={agent} disabled={dirty || saving || providersLoading || !!providersError} onUpdated={onVerified} />
      </section>
      <section className="settings-agent-editor-section">
        <h3>Generation parameters</h3>
        <p className="settings-hint">Leave a field empty to use the default value.</p>
        <div className="settings-agent-parameters">
          <div className="settings-agent-parameter">
            <label className="ui-text-input">
            <span className="ui-item-legend">Temperature</span>
            <input className="ui-input" type="number" min="0" max="2" step="any" value={temperature} placeholder="Default" disabled={saving}
              aria-invalid={!temperatureValid} onChange={(event) => { setTemperature(event.target.value); setError("") }} />
            </label>
            <span className="settings-hint">0ΓÇô2 ┬╖ Lower values produce more consistent results.</span>
          </div>
          <div className="settings-agent-parameter">
            <label className="ui-text-input">
             <span className="ui-item-legend">Maximum output tokens per call</span>
             <input className="ui-input" type="number" min="1" max="2147483647" step="1" value={maxTokens} placeholder="Default: 1,000" disabled={saving}
              aria-invalid={!tokensValid} onChange={(event) => { setMaxTokens(event.target.value); setError("") }} />
            </label>
             <span className="settings-hint">Limits the output of each model call. The backend default is 1,000 tokens.</span>
          </div>
        </div>
        {!temperatureValid && <p className="settings-error" role="alert">Temperature must be between 0 and 2.</p>}
        {!tokensValid && <p className="settings-error" role="alert">Maximum tokens must be a positive integer, up to 2147483647.</p>}
      </section>
      <section className="settings-agent-editor-section">
        <h3>Execution token budget</h3>
        <p className="settings-hint">Counts input and output across all model calls. Leave a field empty to clear its override.</p>
        <div className="settings-agent-parameters">
          <div className="settings-agent-parameter">
          <label className="ui-text-input">
            <span className="ui-item-legend">Initial token budget</span>
             <input className="ui-input" type="number" min="1" max="2147483647" step="1" value={tokenBudget} placeholder={`Default: ${DEFAULT_TOKEN_BUDGET.toLocaleString()}`} disabled={saving}
              aria-invalid={!budgetValid || !limitsValid} onChange={(event) => { setTokenBudget(event.target.value); setError("") }} />
          </label>
          <span className="settings-hint">Default initial budget: {DEFAULT_TOKEN_BUDGET.toLocaleString()} tokens.</span>
          </div>
          <div className="settings-agent-parameter">
          <label className="ui-text-input">
            <span className="ui-item-legend">Absolute token limit</span>
             <input className="ui-input" type="number" min="1" max="2147483647" step="1" value={absoluteTokenLimit} placeholder={`Default: ${DEFAULT_ABSOLUTE_TOKEN_LIMIT.toLocaleString()}`} disabled={saving}
              aria-invalid={!absoluteValid || !limitsValid} onChange={(event) => { setAbsoluteTokenLimit(event.target.value); setError("") }} />
          </label>
          <span className="settings-hint">Default absolute limit: {DEFAULT_ABSOLUTE_TOKEN_LIMIT.toLocaleString()} tokens.</span>
          </div>
        </div>
        {(!budgetValid || !absoluteValid) && <p className="settings-error" role="alert">Token limits must be positive integers, up to 2147483647.</p>}
        {budgetValid && absoluteValid && !limitsValid && <p className="settings-error" role="alert">The absolute limit must be greater than or equal to the initial budget.</p>}
        {budgetValid && absoluteValid && limitsValid && <p className="settings-hint">
          Tolerance margin: {(effectiveAbsolute - effectiveBudget).toLocaleString()} tokens ({new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format((effectiveAbsolute - effectiveBudget) / effectiveBudget * 100)}%).
          {effectiveAbsolute === effectiveBudget && " Strict budget: no additional margin."}
        </p>}
      </section>
      <section className="settings-agent-editor-section">
        <div className="settings-agent-options-heading">
          <h3>Agent-specific options</h3>
          <Badge tone="info">Coming soon</Badge>
        </div>
        <div className="settings-agent-options-placeholder">
          <p>Custom settings for {agent.agentType}</p>
          <p className="settings-hint">Additional options specific to this agent will appear here when available.</p>
        </div>
      </section>
    </form>
  </Drawer>
}

import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, saveAgentSettings, type AgentSettings, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Drawer, ItemSelector } from "../../shared/ui-kit/index.ts"
import { AgentAccessVerification } from "./AgentAccessVerification.tsx"
import { DEFAULT_TOKEN_BUDGET, DEFAULT_ABSOLUTE_TOKEN_LIMIT } from "../../shared/agent-monitor/tokenBudgets.ts"
import { formatNumber } from "../../shared/i18n/format.ts"
import { configFields, getAuditSettings } from "./auditSettingsApi.ts"

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
  const { t } = useTranslation("settings")
  const [modelId, setModelId] = useState<number | null>(agent.configuration?.model.id ?? null)
  const [credentialId, setCredentialId] = useState<number | null>(agent.configuration?.credential.id ?? null)
  const [temperature, setTemperature] = useState(String(agent.configuration?.temperature ?? ""))
  const [maxTokens, setMaxTokens] = useState(String(agent.configuration?.maxTokens ?? ""))
  const [tokenBudget, setTokenBudget] = useState(String(agent.configuration?.tokenBudget ?? ""))
  const [absoluteTokenLimit, setAbsoluteTokenLimit] = useState(String(agent.configuration?.absoluteTokenLimit ?? ""))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<{ key: ParseKeys<"settings">, detail?: string } | null>(null)
  const categoryKey = (agent.qualityAttributes ?? []).join(",")
  const inheritanceKey = `${agent.agentType}:${categoryKey}`
  const [inheritance, setInheritance] = useState<{ key: string, values: Array<{ attribute: string, value: number, minimum: number }>, error: boolean } | null>(null)
  const inheritedOutputs = inheritance?.key === inheritanceKey ? inheritance.values : []
  const inheritanceError = inheritance?.key === inheritanceKey && inheritance.error
  const inheritanceLoading = !!categoryKey && inheritance?.key !== inheritanceKey
  useEffect(() => {
    if (!open || !categoryKey) return
    const controller = new AbortController()
    Promise.all(categoryKey.split(",").map(async (attribute) => {
      const descriptor = await getAuditSettings(attribute, controller.signal)
      const fields = configFields(descriptor.schema)
      const output = fields.find((field) => field.path.join(".") === "agent_defaults.max_output_tokens")
      const defaults = descriptor.values["agent_defaults"] as Record<string, unknown> | undefined
      const specific = descriptor.values["security_config"] as Record<string, unknown> | undefined
      const value = (attribute === "security" ? specific?.["max_output_tokens"] : undefined)
        ?? defaults?.["max_output_tokens"] ?? output?.schema.default
      return typeof value === "number" ? { attribute, value, minimum: output?.schema.minimum ?? 1 } : null
    })).then((values) => {
      if (!controller.signal.aborted) setInheritance({ key: inheritanceKey, values: values.filter((value) => value !== null), error: false })
    }).catch(() => {
      if (!controller.signal.aborted) setInheritance({ key: inheritanceKey, values: [], error: true })
    })
    return () => controller.abort()
  }, [open, categoryKey, inheritanceKey])

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
      setError(null)
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
  const outputMinimum = Math.max(1, ...inheritedOutputs.map((entry) => entry.minimum))
  const tokensValid = numericMaxTokens === null || (Number.isInteger(numericMaxTokens) && numericMaxTokens >= outputMinimum && numericMaxTokens <= 2147483647)
  const inheritedValue = inheritedOutputs.length && inheritedOutputs.every((entry) => entry.value === inheritedOutputs[0]?.value)
    ? inheritedOutputs[0]?.value : undefined
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
    setError(null)
    try {
      const updated = await saveAgentSettings(agent.agentType, modelId, credentialId, {
        temperature: numericTemperature, maxTokens: numericMaxTokens,
        tokenBudget: numericBudget, absoluteTokenLimit: numericAbsolute,
      })
      onSaved(updated)
      onClose()
    } catch (failure) {
      setError(failure instanceof ApiError && failure.messageSource !== "client"
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
      : "agents.status.notConfigured"

  return <Drawer
    open={open}
    title={t("agents.drawer.title", { agentType: agent.agentType })}
    description={t("agents.drawer.description")}
    onClose={() => { if (!saving) onClose() }}
    footer={<>
      <Button variant="secondary" disabled={saving} onClick={onClose}>{t("agents.drawer.cancel")}</Button>
      <Button disabled={!canSave} loading={saving} loadingText={t("agents.drawer.saving")} onClick={() => void save()}>{t("agents.drawer.saveChanges")}</Button>
    </>}
  >
    <form className="settings-agent-editor" onSubmit={(event) => { event.preventDefault(); void save() }}>
      <div className="settings-agent-drawer-summary">
        <span className="settings-agent-drawer-name">{agent.agentType}</span>
        <Badge tone={dirty ? "info" : agent.configured ? "success" : "info"}>{t(statusKey)}</Badge>
      </div>
      {(error || providersError) && <p className="settings-error" role="alert">{error ? error.detail === undefined ? t(error.key) : t(error.key, { detail: error.detail }) : providersError}</p>}
      <section className="settings-agent-editor-section">
        <h3>{t("agents.drawer.modelAccess")}</h3>
        <p className="settings-hint">{t("agents.drawer.modelAccessHint")}</p>
        <ItemSelector label={t("agents.form.model")} items={models.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.providerName }))}
          selectedId={modelId === null ? null : String(modelId)} placeholder={t("agents.form.selectModel")} emptyText={t("agents.form.noModels")}
          onSelect={(id) => {
            const next = models.find((entry) => entry.id === Number(id))
            if (next?.providerId !== model?.providerId) setCredentialId(null)
            setModelId(Number(id)); setError(null)
          }} hasMore={false} onLoadMore={() => {}} loading={providersLoading} disabled={saving || !!providersError} />
        <ItemSelector label={t("agents.form.credential")} items={credentials.map((entry) => ({ id: String(entry.id), label: entry.name, detail: entry.apiKeyPreview }))}
          selectedId={credentialId === null ? null : String(credentialId)} placeholder={model ? t("agents.form.selectCredential") : t("agents.form.selectModelFirst")}
          emptyText={t("agents.form.noCredentialsForProvider")} onSelect={(id) => { setCredentialId(Number(id)); setError(null) }}
          hasMore={false} onLoadMore={() => {}} disabled={!model || providersLoading || saving || !!providersError} />
        <AgentAccessVerification agent={agent} disabled={dirty || saving || providersLoading || !!providersError} onUpdated={onVerified} />
      </section>
      <section className="settings-agent-editor-section">
        <h3>{t("agents.drawer.generation")}</h3>
        <p className="settings-hint">{t("agents.drawer.generationHint")}</p>
        <div className="settings-agent-parameters">
          <div className="settings-agent-parameter">
            <label className="ui-text-input">
            <span className="ui-item-legend">{t("agents.drawer.temperature")}</span>
            <input className="ui-input" type="number" min="0" max="2" step="any" value={temperature} placeholder={t("agents.drawer.defaultPlaceholder")} disabled={saving}
              aria-invalid={!temperatureValid} onChange={(event) => { setTemperature(event.target.value); setError(null) }} />
            </label>
            <span className="settings-hint">{t("agents.drawer.temperatureHint")}</span>
          </div>
          <div className="settings-agent-parameter">
            <label className="ui-text-input">
             <span className="ui-item-legend">{t("agents.drawer.maxTokens")}</span>
             <input className="ui-input" type="number" min={outputMinimum} max="2147483647" step="1" value={maxTokens}
               placeholder={inheritedValue === undefined ? t("agents.drawer.defaultPlaceholder") : String(inheritedValue)} disabled={saving}
              aria-invalid={!tokensValid} onChange={(event) => { setMaxTokens(event.target.value); setError(null) }} />
            </label>
             <span className="settings-hint">{t("agents.drawer.maxTokensHint")}</span>
             {inheritanceLoading && <span className="settings-hint">{t("agents.drawer.outputInheritanceLoading")}</span>}
             {inheritanceError && <span className="settings-error" role="alert">{t("agents.drawer.outputInheritanceError")}</span>}
             {!inheritanceLoading && !inheritanceError && inheritedOutputs.map(({ attribute, value }) => <span className="settings-hint" key={attribute}>
               {t(numericMaxTokens === null ? "agents.drawer.outputInherited" : "agents.drawer.outputOverridden", {
                 category: attribute === "maintainability" ? t("audit.allAgents") : attribute === "security" ? t("audit.security") : t("audit.functionalAdequacy"),
                 value: formatNumber(numericMaxTokens ?? value), inherited: formatNumber(value),
               })}
             </span>)}
          </div>
        </div>
        {!temperatureValid && <p className="settings-error" role="alert">{t("agents.drawer.temperatureInvalid")}</p>}
        {!tokensValid && <p className="settings-error" role="alert">{t("agents.drawer.maxTokensInvalid")}</p>}
      </section>
      <section className="settings-agent-editor-section">
        <h3>{t("agents.drawer.tokenBudget")}</h3>
        <p className="settings-hint">{t("agents.drawer.tokenBudgetHint")}</p>
        <div className="settings-agent-parameters">
          <div className="settings-agent-parameter">
          <label className="ui-text-input">
            <span className="ui-item-legend">{t("agents.drawer.initialBudget")}</span>
             <input className="ui-input" type="number" min="1" max="2147483647" step="1" value={tokenBudget} placeholder={t("agents.drawer.initialBudgetPlaceholder", { default: formatNumber(DEFAULT_TOKEN_BUDGET) })} disabled={saving}
              aria-invalid={!budgetValid || !limitsValid} onChange={(event) => { setTokenBudget(event.target.value); setError(null) }} />
          </label>
          <span className="settings-hint">{t("agents.drawer.initialBudgetHint", { default: formatNumber(DEFAULT_TOKEN_BUDGET) })}</span>
          </div>
          <div className="settings-agent-parameter">
          <label className="ui-text-input">
            <span className="ui-item-legend">{t("agents.drawer.absoluteLimit")}</span>
             <input className="ui-input" type="number" min="1" max="2147483647" step="1" value={absoluteTokenLimit} placeholder={t("agents.drawer.absoluteLimitPlaceholder", { default: formatNumber(DEFAULT_ABSOLUTE_TOKEN_LIMIT) })} disabled={saving}
              aria-invalid={!absoluteValid || !limitsValid} onChange={(event) => { setAbsoluteTokenLimit(event.target.value); setError(null) }} />
          </label>
          <span className="settings-hint">{t("agents.drawer.absoluteLimitHint", { default: formatNumber(DEFAULT_ABSOLUTE_TOKEN_LIMIT) })}</span>
          </div>
        </div>
        {(!budgetValid || !absoluteValid) && <p className="settings-error" role="alert">{t("agents.drawer.tokenLimitsInvalid")}</p>}
        {budgetValid && absoluteValid && !limitsValid && <p className="settings-error" role="alert">{t("agents.drawer.limitsOrderInvalid")}</p>}
        {budgetValid && absoluteValid && limitsValid && <p className="settings-hint">
          {t(effectiveAbsolute === effectiveBudget ? "agents.drawer.toleranceMarginStrict" : "agents.drawer.toleranceMargin", { margin: formatNumber(effectiveAbsolute - effectiveBudget), percent: formatNumber((effectiveAbsolute - effectiveBudget) / effectiveBudget * 100, { maximumFractionDigits: 1 }) })}
        </p>}
      </section>
      <section className="settings-agent-editor-section">
        <div className="settings-agent-options-heading">
          <h3>{t("agents.drawer.agentOptions")}</h3>
          <Badge tone="info">{t("agents.drawer.comingSoon")}</Badge>
        </div>
        <div className="settings-agent-options-placeholder">
          <p>{t("agents.drawer.customSettings", { agentType: agent.agentType })}</p>
          <p className="settings-hint">{t("agents.drawer.agentOptionsHint")}</p>
        </div>
      </section>
    </form>
  </Drawer>
}

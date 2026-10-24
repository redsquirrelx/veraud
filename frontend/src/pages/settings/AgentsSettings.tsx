import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, listAgentSettings, syncAgentSettings, type AgentSettings, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"
import { Button, Panel, Spinner } from "../../shared/ui-kit/index.ts"
import { AgentSettingsCard } from "./AgentSettingsCard.tsx"
import { AgentSettingsDrawer } from "./AgentSettingsDrawer.tsx"
import { AuditSettingsDrawer } from "./AuditSettingsDrawer.tsx"

interface AgentsSettingsProps {
  providers?: AiProviderDetail[]
  providersLoading?: boolean
  providersError?: string
  onAssignmentsSaved?: (agent: AgentSettings) => void
  agentTypes?: readonly string[]
  heading?: string
  description?: string
  labels?: Record<string, string>
  modelAccessOnly?: boolean
  qualityCategories?: boolean
}

// Backend failures are stored as translation keys (plus the backend detail)
// so the message follows language changes.
interface AgentsLoadError {
  key: ParseKeys<"settings">
  detail?: string
}

function agentsLoadError(failure: unknown): AgentsLoadError {
  return failure instanceof ApiError && failure.messageSource !== "client"
    ? { key: "agents.loadFailedWithDetail", detail: failure.message }
    : { key: "agents.loadFailed" }
}

export function AgentsSettings({ providers = [], providersLoading = false, providersError = "", onAssignmentsSaved,
  agentTypes, heading, description, labels = {}, modelAccessOnly = false, qualityCategories = false,
}: AgentsSettingsProps) {
  const { t } = useTranslation("settings")
  const [agents, setAgents] = useState<AgentSettings[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<AgentsLoadError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [selectedAgent, setSelectedAgent] = useState<AgentSettings | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [synchronizing, setSynchronizing] = useState(false)
  const [syncError, setSyncError] = useState<AgentsLoadError | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    listAgentSettings(controller.signal).then(
      (rows) => {
        if (controller.signal.aborted) return
        setAgents(rows)
        setLoading(false)
      },
      (failure: unknown) => {
        if (controller.signal.aborted) return
        setError(agentsLoadError(failure))
        setLoading(false)
      },
    )
    return () => controller.abort()
  }, [attempt])

  function retry() {
    setLoading(true)
    setError(null)
    setAttempt((current) => current + 1)
  }

  function saved(updated: AgentSettings) {
    verified(updated)
    onAssignmentsSaved?.(updated)
  }

  function verified(updated: AgentSettings) {
    setAgents((current) => current.map((row) => row.agentType === updated.agentType ? updated
      : updated.modelConfigurationAgentType && row.modelConfigurationAgentType === updated.modelConfigurationAgentType
        ? { ...row, configuration: updated.configuration, configured: updated.configured, verification: updated.verification } : row))
    setSelectedAgent((current) => current?.agentType === updated.agentType ? updated : current)
  }

  async function synchronize() {
    if (synchronizing) return
    setSynchronizing(true)
    setSyncError(null)
    try {
      setAgents(await syncAgentSettings())
      setError(null)
    } catch (failure) {
      setSyncError(agentsLoadError(failure))
    } finally { setSynchronizing(false) }
  }

  const categories = [...new Set(agents.flatMap((agent) => agent.qualityAttributes ?? []))].sort()
    .flatMap((attribute) => {
      const members = agents.filter((agent) => agent.qualityAttributes?.includes(attribute) && agent.requiresModel !== false
        && (agent.availability === undefined || agent.availability === "available"))
      const owners = agents.filter((agent) => members.some((member) => (member.modelConfigurationAgentType ?? member.agentType) === agent.agentType)
        && agent.requiresModel !== false && (agent.availability === undefined || agent.availability === "available"))
      const representative = owners.find((agent) => agent.role === "manager") ?? owners.find((agent) => agent.executionModes?.includes("direct")) ?? owners[0]
      return representative ? [{ attribute, agent: representative, mixed: owners.some((agent) =>
        agent.configuration?.model.id !== representative.configuration?.model.id || agent.configuration?.credential.id !== representative.configuration?.credential.id) }] : []
    })
  const cards = qualityCategories ? categories : agents.filter((agent) => !agentTypes || agentTypes.includes(agent.agentType))
    .map((agent) => ({ agent, attribute: undefined, mixed: false }))

  return (
    <div className="settings-agents">
      <Panel>
        <div className="settings-agents-heading">
          <h2>{heading ?? t("agents.title")}</h2>
          <p className="settings-hint">{description ?? t("agents.subtitle")}</p>
          {providersError && <p className="settings-error" role="alert">{providersError}</p>}
          {qualityCategories && <Button variant="secondary" disabled={loading || synchronizing} loading={synchronizing}
            loadingText={t("audit.synchronizingCatalog")} onClick={() => void synchronize()}>{t("audit.syncCatalog")}</Button>}
          {syncError && <p className="settings-error" role="alert">{syncError.detail === undefined ? t(syncError.key) : t(syncError.key, { detail: syncError.detail })}</p>}
        </div>
        {loading ? <Spinner /> : error ? (
          <div className="settings-agent-editor" role="alert">
            <p className="settings-error">{error.detail === undefined ? t(error.key) : t(error.key, { detail: error.detail })}</p>
            <Button variant="secondary" onClick={retry}>{t("agents.retry")}</Button>
          </div>
        ) : cards.length === 0 ? (
          <p className="settings-hint" role="status">{t(qualityCategories ? "audit.noCategories" : "agents.empty")}</p>
        ) : (
          <div className="settings-agents-grid">
            {cards.map(({ agent, attribute, mixed }) => (
              <AgentSettingsCard
                key={attribute ?? agent.agentType}
                agent={agent}
                label={attribute ? labels[attribute] ?? attribute : labels[agent.agentType]}
                qualityAttribute={attribute}
                categoryMixed={mixed}
                onCategorySaved={setAgents}
                modelAccessOnly={modelAccessOnly}
                providers={providers}
                providersLoading={providersLoading || !!providersError || synchronizing}
                onSaved={saved}
                onVerified={verified}
                 onConfigure={() => {
                    if (attribute) { setSelectedCategory(attribute); return }
                    setSelectedAgent(agent)
                    setDrawerOpen(true)
                }}
              />
            ))}
          </div>
        )}
      </Panel>
      {selectedCategory && <AuditSettingsDrawer key={selectedCategory} attribute={selectedCategory}
        label={labels[selectedCategory] ?? selectedCategory} open onClose={() => setSelectedCategory(null)} />}
      {selectedAgent && <AgentSettingsDrawer
        agent={selectedAgent}
        open={drawerOpen}
        providers={providers}
        providersLoading={providersLoading}
        providersError={providersError}
        onClose={() => setDrawerOpen(false)}
        onSaved={saved}
        onVerified={verified}
      />}
    </div>
  )
}

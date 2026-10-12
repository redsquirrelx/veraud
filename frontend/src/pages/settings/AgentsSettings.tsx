import { useEffect, useState } from "react"
import { ApiError, listAgentSettings, type AgentSettings, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"
import { Button, Panel, Spinner } from "../../shared/ui-kit/index.ts"
import { AgentSettingsCard } from "./AgentSettingsCard.tsx"
import { AgentSettingsDrawer } from "./AgentSettingsDrawer.tsx"

interface AgentsSettingsProps {
  providers?: AiProviderDetail[]
  providersLoading?: boolean
  providersError?: string
  onAssignmentsSaved?: (agent: AgentSettings) => void
}

export function AgentsSettings({ providers = [], providersLoading = false, providersError = "", onAssignmentsSaved }: AgentsSettingsProps) {
  const [agents, setAgents] = useState<AgentSettings[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [attempt, setAttempt] = useState(0)
  const [selectedAgent, setSelectedAgent] = useState<AgentSettings | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

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
        setError(failure instanceof ApiError ? failure.message : "Could not load agent settings")
        setLoading(false)
      },
    )
    return () => controller.abort()
  }, [attempt])

  function retry() {
    setLoading(true)
    setError("")
    setAttempt((current) => current + 1)
  }

  function saved(updated: AgentSettings) {
    verified(updated)
    onAssignmentsSaved?.(updated)
  }

  function verified(updated: AgentSettings) {
    setAgents((current) => current.map((row) => row.agentType === updated.agentType ? updated : row))
    setSelectedAgent((current) => current?.agentType === updated.agentType ? updated : current)
  }

  return (
    <div className="settings-agents">
      <Panel>
        <div className="settings-agents-heading">
          <h2>Agent configuration</h2>
          <p className="settings-hint">Agent types declared in the backend and their saved configuration.</p>
          {providersError && <p className="settings-error" role="alert">{providersError}</p>}
        </div>
        {loading ? <Spinner /> : error ? (
          <div className="settings-agent-editor" role="alert">
            <p className="settings-error">{error}</p>
            <Button variant="secondary" onClick={retry}>Retry</Button>
          </div>
        ) : agents.length === 0 ? (
          <p className="settings-hint">No agent types are declared in the backend.</p>
        ) : (
          <div className="settings-agents-grid">
            {agents.map((agent) => (
              <AgentSettingsCard
                key={agent.agentType}
                agent={agent}
                providers={providers}
                providersLoading={providersLoading || !!providersError}
                onSaved={saved}
                onVerified={verified}
                onConfigure={() => {
                    setSelectedAgent(agent)
                    setDrawerOpen(true)
                }}
              />
            ))}
          </div>
        )}
      </Panel>
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

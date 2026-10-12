import { useState } from "react"
import { ApiError, verifyAgentSettings, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button } from "../../shared/ui-kit/index.ts"

export function AgentAccessVerification({ agent, disabled, onUpdated }: { agent: AgentSettings, disabled: boolean, onUpdated: (agent: AgentSettings) => void }) {
  const [verifying, setVerifying] = useState(false)
  const [error, setError] = useState("")
  const verification = agent.verification
  async function verify() {
    if (verifying || disabled || !agent.configured) return
    setVerifying(true)
    setError("")
    try { onUpdated(await verifyAgentSettings(agent.agentType)) }
    catch (failure) { setError(failure instanceof ApiError ? failure.message : "Could not verify model access") }
    finally { setVerifying(false) }
  }
  return <div className="settings-agent-verification">
    <div className="settings-agent-options-heading">
      <Badge tone={verification?.status === "verified" ? "success" : verification?.status === "failed" ? "warning" : "info"}>
        {verification?.status === "verified" ? "Verified" : verification?.status === "failed" ? "Needs attention" : "Not verified"}
      </Badge>
      <Button variant="secondary" disabled={disabled || !agent.configured || verifying} loading={verifying} loadingText="Verifying..." onClick={() => void verify()}>Verify access</Button>
    </div>
    {verification?.checkedAt && <p className="settings-hint">Last checked: {new Date(verification.checkedAt).toLocaleString()}</p>}
    {(error || verification?.message) && <p className="settings-error" role="alert">{error || verification?.message}</p>}
    <p className="settings-hint">Checks saved model access with a minimal provider request. Every execution checks again before starting.</p>
    {disabled && <p className="settings-hint">Save your changes before verifying access.</p>}
  </div>
}

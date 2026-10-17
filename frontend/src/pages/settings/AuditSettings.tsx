import { useState } from "react"
import { Button, Panel } from "../../shared/ui-kit/index.ts"
import {
  AUDIT_CONFIGURATION_PLACEHOLDER,
  MIN_CONTEXT_CHARACTERS,
  MIN_TOTAL_TOKENS,
  auditLimitForm,
  parseLimit,
  sharedBudgetFits,
  sharedBudgetHeadroom,
  type AuditLimitForm,
} from "./auditConfiguration.ts"

function tokens(value: number | null): string {
  return value === null ? "" : value.toLocaleString()
}

const PRISTINE_FORM = auditLimitForm(AUDIT_CONFIGURATION_PLACEHOLDER)

function isEdited(form: AuditLimitForm): boolean {
  return form.contextCharacters !== PRISTINE_FORM.contextCharacters
    || form.agentTokens !== PRISTINE_FORM.agentTokens
    || form.auditTokens !== PRISTINE_FORM.auditTokens
}

/** Audit operating limits. The values live in memory until an endpoint backs
 *  this tab, so the request body is shown instead of being sent. */
export function AuditSettings() {
  const [form, setForm] = useState<AuditLimitForm>(PRISTINE_FORM)

  function edit(field: keyof AuditLimitForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  function reset() {
    setForm(PRISTINE_FORM)
  }

  const contextCharacters = parseLimit(form.contextCharacters, MIN_CONTEXT_CHARACTERS)
  const agentTokens = parseLimit(form.agentTokens, MIN_TOTAL_TOKENS)
  const auditTokens = parseLimit(form.auditTokens, MIN_TOTAL_TOKENS)
  const headroom = sharedBudgetHeadroom(auditTokens, agentTokens)
  const budgetFitsAgent = sharedBudgetFits(auditTokens, agentTokens)
  const dirty = isEdited(form)

  return (
    <div className="settings-agents">
      <Panel>
        <div className="settings-agents-heading">
          <h2>Audit configuration</h2>
          <p className="settings-hint">Limits applied to the agents that take part in a maintainability audit.</p>
        </div>
        <div className="settings-agent-editor">
          <section className="settings-agent-editor-section">
            <h3>Agent defaults</h3>
            <p className="settings-hint">Applied to every manager, coordinator and investigator of the audit.</p>
            <div className="settings-agent-parameters">
              <div className="settings-agent-parameter">
                <label className="ui-text-input">
                  <span className="ui-item-legend">Context characters per call</span>
                  <input
                    className="ui-input"
                    type="number"
                    min={MIN_CONTEXT_CHARACTERS}
                    max={2147483647}
                    step="1"
                    value={form.contextCharacters}
                    aria-invalid={contextCharacters === null}
                    onChange={(event) => edit("contextCharacters", event.target.value)}
                  />
                </label>
                <span className="settings-hint">Repository characters a single model call may carry.</span>
              </div>
              <div className="settings-agent-parameter">
                <label className="ui-text-input">
                  <span className="ui-item-legend">Personal token allowance</span>
                  <input
                    className="ui-input"
                    type="number"
                    min={MIN_TOTAL_TOKENS}
                    max={2147483647}
                    step="1"
                    value={form.agentTokens}
                    aria-invalid={agentTokens === null}
                    onChange={(event) => edit("agentTokens", event.target.value)}
                  />
                </label>
                <span className="settings-hint">Tokens one agent may spend on its own. Descendants never consume their parent's allowance.</span>
              </div>
            </div>
            {contextCharacters === null && <p className="settings-error" role="alert">Context characters must be a whole number of {MIN_CONTEXT_CHARACTERS.toLocaleString()} or more.</p>}
            {agentTokens === null && <p className="settings-error" role="alert">The personal allowance must be a whole number of {MIN_TOTAL_TOKENS.toLocaleString()} tokens or more.</p>}
          </section>
          <section className="settings-agent-editor-section">
            <h3>Shared audit budget</h3>
            <p className="settings-hint">Enforced across every agent of the audit together, however many run at once.</p>
            <div className="settings-agent-parameters">
              <div className="settings-agent-parameter">
                <label className="ui-text-input">
                  <span className="ui-item-legend">Total tokens</span>
                  <input
                    className="ui-input"
                    type="number"
                    min={MIN_TOTAL_TOKENS}
                    max={2147483647}
                    step="1"
                    value={form.auditTokens}
                    aria-invalid={auditTokens === null || !budgetFitsAgent}
                    onChange={(event) => edit("auditTokens", event.target.value)}
                  />
                </label>
                <span className="settings-hint">Caps the whole run, not a single agent.</span>
              </div>
            </div>
            {auditTokens === null && <p className="settings-error" role="alert">The shared budget must be a whole number of {MIN_TOTAL_TOKENS.toLocaleString()} tokens or more.</p>}
            {auditTokens !== null && !budgetFitsAgent && <p className="settings-error" role="alert">The shared budget is below one agent's personal allowance, so no agent could ever reach its own limit.</p>}
            {headroom !== null && budgetFitsAgent && <p className="settings-hint">
              Headroom: {tokens(headroom)} tokens left for the rest of the audit after one agent spends its full allowance.
            </p>}
          </section>
        </div>
        <div className="settings-agent-footer">
          <Button variant="secondary" disabled={!dirty} onClick={reset}>Reset</Button>
        </div>
      </Panel>
    </div>
  )
}

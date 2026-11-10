import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../shared/ui-kit/index.ts"
import type { AuditAgentCatalog } from "./auditAgentCatalog.ts"
import { getQualityAuditConfiguration } from "./qualityAuditApi.ts"
import { reuseAuditSelection, type ReusedAuditSelection } from "./reuseAuditSelection.ts"
import { listAgentSettings } from "../../infrastructure/http-client/httpClient.ts"

export function ReuseAuditConfiguration({ projectId, auditId, available, catalog, lazyCatalog = false, disabled, onReuse, hideTrigger = false, onRegisterReuse }: {
  projectId: number, auditId: number, available: boolean, catalog: AuditAgentCatalog,
  lazyCatalog?: boolean, disabled: boolean, onReuse: (selection: ReusedAuditSelection) => void,
  hideTrigger?: boolean, onRegisterReuse?: (reuse: () => Promise<void>) => void,
}) {
  const { t } = useTranslation("projects")
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  async function reuse() {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setLoading(true)
    setFailed(false)
    try {
      const [history, agents] = await Promise.all([
        getQualityAuditConfiguration(projectId, auditId, controller.signal),
        lazyCatalog ? listAgentSettings(controller.signal) : Promise.resolve(catalog.agents),
      ])
      if (controller.signal.aborted) return
      if (history.configuration?.version !== 1) throw new Error("Configuration unavailable")
      onReuse(reuseAuditSelection(history.configuration, agents))
    } catch {
      if (!controller.signal.aborted) setFailed(true)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
      request.current = null
    }
  }

  // Keep the latest trigger registered for menu-driven reuse in the history explorer.
  useEffect(() => { onRegisterReuse?.(reuse) })

  return <div className="quality-audit-reuse">
    {!hideTrigger && <Button variant="secondary" disabled={!available || (!lazyCatalog && (catalog.loading || catalog.failed)) || disabled} loading={loading}
      title={!available ? t("qualityAudits.configurationHistory.unavailable") : undefined}
      onClick={() => void reuse()}>{t("qualityAudits.configurationHistory.reuse")}</Button>}
    {failed && <p className="label" role="alert">{t("qualityAudits.configurationHistory.reuseFailed")}</p>}
  </div>
}

import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../shared/ui-kit/index.ts"
import type { AuditAgentCatalog } from "./auditAgentCatalog.ts"
import { getQualityAuditConfiguration } from "./qualityAuditApi.ts"
import { reuseAuditSelection, type ReusedAuditSelection } from "./reuseAuditSelection.ts"

export function ReuseAuditConfiguration({ projectId, auditId, available, catalog, disabled, onReuse }: {
  projectId: number, auditId: number, available: boolean, catalog: AuditAgentCatalog,
  disabled: boolean, onReuse: (selection: ReusedAuditSelection) => void,
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
      const history = await getQualityAuditConfiguration(projectId, auditId, controller.signal)
      if (controller.signal.aborted) return
      if (history.configuration?.version !== 1) throw new Error("Configuration unavailable")
      onReuse(reuseAuditSelection(history.configuration, catalog.agents))
    } catch {
      if (!controller.signal.aborted) setFailed(true)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
      request.current = null
    }
  }

  return <div className="quality-audit-reuse">
    <Button variant="secondary" disabled={!available || catalog.loading || catalog.failed || disabled} loading={loading}
      title={!available ? t("qualityAudits.configurationHistory.unavailable") : undefined}
      onClick={() => void reuse()}>{t("qualityAudits.configurationHistory.reuse")}</Button>
    {failed && <p className="label" role="alert">{t("qualityAudits.configurationHistory.reuseFailed")}</p>}
  </div>
}

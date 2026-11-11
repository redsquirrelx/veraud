import { useEffect, useState } from "react"
import type { ParseKeys, TFunction } from "i18next"
import { useTranslation } from "react-i18next"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Drawer, Spinner } from "../../shared/ui-kit/index.ts"
import { completionStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"
import { AuditAttributeSummary } from "./AuditAttributeSummary.tsx"
import { getQualityAuditConfiguration, type AuditConfigurationHistory, type AuditRunConfiguration } from "./qualityAuditApi.ts"

const attributeLabels: Record<string, ParseKeys<"projects">> = {
  maintainability: "auditStatus.pipelines.maintainability", security: "auditStatus.pipelines.security",
  functional_adequacy: "auditStatus.pipelines.functionalAdequacy",
}
const invocationLabels: Record<string, ParseKeys<"projects">> = {
  running: "qualityAudits.configurationHistory.running", completed: "qualityAudits.configurationHistory.completed",
  failed: "qualityAudits.configurationHistory.failed", skipped: "qualityAudits.configurationHistory.skipped",
  cancelled: "qualityAudits.configurationHistory.cancelled",
}

function enumText(t: TFunction<"projects", undefined>, keys: Record<string, ParseKeys<"projects">>, value: string): string {
  const key = statusLabelKey(keys, value)
  return key === null ? value : t(key)
}

/** Rebuild display-only relationships from the saved snapshot, never today's catalog. */
function savedCatalog(configuration: AuditRunConfiguration): AgentSettings[] {
  const agents = new Map<string, AgentSettings>()
  function add(id: string, name: string, attribute: string, children: string[] = [], role?: string) {
    agents.set(id, { agentType: id, name, role, childAgentTypes: children, availability: "available",
      qualityAttributes: [attribute], workflowIds: [], configured: false, configuration: null })
  }
  for (const scope of configuration.scopes) {
    for (const agent of scope.requiredAgents) add(agent.id, agent.name, scope.id)
    for (const child of scope.subcharacteristics) {
      add(child.id, child.name, scope.id, child.investigators.map((agent) => agent.id), "coordinator")
      for (const agent of child.investigators) add(agent.id, agent.name, scope.id, [], "investigator")
    }
    for (const agent of [...scope.techniques, ...scope.investigators]) add(agent.id, agent.name, scope.id)
    if (scope.id !== "maintainability") {
      const root = scope.requiredAgents[0]
      if (root) add(root.id, root.name, scope.id, scope.techniques.map((agent) => agent.id))
    }
  }
  return [...agents.values()]
}

export function AuditConfigurationDetails({ projectId, auditId, available, open, onOpenChange, hideTrigger = false }: {
  projectId: number, auditId: number, available: boolean
  open?: boolean, onOpenChange?: (open: boolean) => void, hideTrigger?: boolean
}) {
  const { t } = useTranslation("projects")
  const [internalOpen, setInternalOpen] = useState(false)
  const drawerOpen = open ?? internalOpen
  const setOpen = onOpenChange ?? setInternalOpen
  const [history, setHistory] = useState<AuditConfigurationHistory | null>(null)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!drawerOpen) return
    const controller = new AbortController()
    getQualityAuditConfiguration(projectId, auditId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setHistory(result)
    }, () => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [drawerOpen, projectId, auditId, attempt])

  const configuration = history?.configuration
  const agents = configuration ? savedCatalog(configuration) : []
  return <>
    {!hideTrigger && <Button variant="secondary" disabled={!available} title={!available ? t("qualityAudits.configurationHistory.unavailable") : undefined}
      onClick={() => { setHistory(null); setFailed(false); setOpen(true) }}>{t("qualityAudits.configurationHistory.view")}</Button>}
    <Drawer open={drawerOpen} title={t("qualityAudits.configurationHistory.title", { id: auditId })} onClose={() => setOpen(false)}>
      {failed ? <div role="alert">
        <p>{t("qualityAudits.configurationHistory.loadFailed")}</p>
        <Button variant="secondary" onClick={() => { setFailed(false); setAttempt((value) => value + 1) }}>{t("qualityAudits.configuration.maintainability.retry")}</Button>
      </div> : !history ? <Spinner /> : !configuration ? <p>{t("qualityAudits.configurationHistory.unavailable")}</p> : <div className="quality-audit-configuration">
        <dl className="quality-audit-saved-revision">
          <div><dt>{t("qualityAudits.configurationHistory.branch")}</dt><dd>{configuration.branch}</dd></div>
          <div><dt>{t("qualityAudits.configurationHistory.commit")}</dt><dd><code>{configuration.commitHash}</code></dd></div>
        </dl>
        {configuration.architectureContext && <section aria-label={t("qualityAudits.configurationHistory.architectureContext")}>
          <h3>{t("qualityAudits.configurationHistory.architectureContext")}</h3>
          <dl className="quality-audit-saved-revision">
            <div><dt>{t("qualityAudits.configurationHistory.architectureContextExecutionId")}</dt><dd><code>#{configuration.architectureContext.executionId}</code></dd></div>
            <div><dt>{t("qualityAudits.configurationHistory.architectureContextProjectVersionId")}</dt><dd>{configuration.architectureContext.projectVersionId}</dd></div>
            <div><dt>{t("qualityAudits.configurationHistory.architectureContextSchemaVersion")}</dt><dd>v{configuration.architectureContext.schemaVersion}</dd></div>
            <div><dt>{t("qualityAudits.configurationHistory.architectureContextExecutionStatus")}</dt><dd><Badge tone={configuration.architectureContext.executionStatus === "complete" ? "success" : "warning"}>{enumText(t, completionStatusLabelKeys, configuration.architectureContext.executionStatus)}</Badge></dd></div>
          </dl>
        </section>}
        {configuration.scopes.map((scope) => <section key={scope.id}>
          <h3>{attributeLabels[scope.id] ? t(attributeLabels[scope.id]) : scope.id}</h3>
          <AuditAttributeSummary attribute={scope.id} catalog={{ agents, loading: false, failed: false, retry: () => {} }}
            selection={Object.fromEntries(scope.subcharacteristics.map((child) => [child.id, child.investigators.map((agent) => agent.id)]))} />
        </section>)}
        <details>
          <summary>{t("qualityAudits.configurationHistory.invocations")}</summary>
          <p className="label">{t("qualityAudits.configurationHistory.scopeNotice")}</p>
          {history.invocations.length ? <ul className="quality-audit-saved-invocations">{history.invocations.map((invocation) => <li key={invocation.id}>
            <span>{agents.find((agent) => agent.agentType === invocation.agentId)?.name ?? invocation.agentId}</span>
            <Badge tone={invocation.status === "failed" ? "warning" : "neutral"}>{invocationLabels[invocation.status] ? t(invocationLabels[invocation.status]) : invocation.status}</Badge>
          </li>)}</ul> : <p className="label">{t("qualityAudits.configurationHistory.noInvocations")}</p>}
        </details>
      </div>}
    </Drawer>
  </>
}

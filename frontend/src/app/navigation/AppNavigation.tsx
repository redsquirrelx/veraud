import { NavLink } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Badge, DropdownLinks, ExternalIcon, ActivityIcon, GridIcon, ShieldIcon, SlidersIcon, Tooltip, type DropdownLinkItem } from "../../shared/ui-kit/index.ts"
import type { ServiceStatus } from "../useBackendStatus.ts"
import { useSettings } from "../settingsContext.tsx"
import { useExecutionExplorer } from "../../shared/execution-explorer/index.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"
import "./AppNavigation.css"

const backendDocsUrl = `${(import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501").replace(/\/+$/, "")}/docs`
const agentServerDocsUrl = `${(import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")}/docs`

export function AppBrand({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation("common")
  return <NavLink to="/" className="app-brand" aria-label={t("navigation.brand")} title={t("navigation.brand")}>
    <ShieldIcon size={18} />
    {!compact && t("navigation.brand")}
  </NavLink>
}

/** Executions currently waiting or running; cancellation is not tracked here. */
const ACTIVE_STATUSES = new Set(["waiting", "running", "cancelling"])

export function AppMainNavigation({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation("common")
  const { openSettings } = useSettings()
  const { openExplorer } = useExecutionExplorer()
  const executions = useAgentExecutions()
  const activeExecutions = executions.filter((execution) => ACTIVE_STATUSES.has(execution.status.toLowerCase())).length
  const executionsLabel = activeExecutions > 0 ? t("navigation.executionsActive", { count: activeExecutions }) : t("navigation.executions")
  return <><nav className="app-nav" aria-label={t("navigation.main")}>
    <Tooltip content={t("navigation.home")} disabled={!compact}>{(props) => <NavLink {...props} to="/" end aria-label={t("navigation.home")} title={compact ? undefined : t("navigation.home")} className={({ isActive }) => isActive ? "app-nav-active" : ""}>
      <GridIcon />
      {!compact && t("navigation.home")}
    </NavLink>}</Tooltip>
    <Tooltip content={t("navigation.executions")} disabled={!compact}>{(props) => <button {...props} type="button" onClick={() => openExplorer()} aria-label={executionsLabel} title={compact ? undefined : t("navigation.executions")}>
      <ActivityIcon />
      {!compact && t("navigation.executions")}
      {activeExecutions > 0 && <span className="app-nav-badge" aria-hidden="true">{activeExecutions}</span>}
    </button>}</Tooltip>
    <Tooltip content={t("navigation.settings")} disabled={!compact}>{(props) => <button {...props} type="button" onClick={() => openSettings()} aria-haspopup="dialog" aria-label={t("navigation.settings")} title={compact ? undefined : t("navigation.settings")}>
      <SlidersIcon />
      {!compact && t("navigation.settings")}
    </button>}</Tooltip>
  </nav></>
}

export function AppDocumentationLinks({ align = "end", compact = false }: { align?: "start" | "end", compact?: boolean }) {
  const { t } = useTranslation("common")
  const documentationLinks: DropdownLinkItem[] = [
    { label: t("navigation.docs.backend"), href: backendDocsUrl, external: true },
    { label: t("navigation.docs.websocket"), href: `${backendDocsUrl}/ws`, external: true },
    { label: t("navigation.docs.agentServer"), href: agentServerDocsUrl, external: true },
  ]
  return <DropdownLinks label={t("navigation.apiDocs")} icon={<ExternalIcon size={14} />} items={documentationLinks} align={align} iconOnly={compact} />
}

const serviceLabelKeys = {
  backend: "navigation.services.backend",
  agentsServer: "navigation.services.agentsServer",
} as const

function StatusBadge({ service, status, compact }: { service: keyof typeof serviceLabelKeys, status: ServiceStatus, compact: boolean }) {
  const { t } = useTranslation("common")
  const online = status === "online"
  const unknown = status === "unknown"
  const text = t("navigation.serviceStatus", {
    label: t(serviceLabelKeys[service]),
    status: t(online ? "navigation.status.online" : unknown ? "navigation.status.unknown" : "navigation.status.offline"),
  })
  return <Badge tone={online ? "success" : unknown ? "unknown" : "danger"}
    dot compact={compact} title={text} aria-label={text}>{text}</Badge>
}

/** Presentational only: the containing layout owns the single status poll. */
export function AppServiceIndicators({ backend, agent, compact = false }: { backend: ServiceStatus, agent: ServiceStatus, compact?: boolean }) {
  return <>
    <StatusBadge service="backend" status={backend} compact={compact} />
    <StatusBadge service="agentsServer" status={agent} compact={compact} />
  </>
}

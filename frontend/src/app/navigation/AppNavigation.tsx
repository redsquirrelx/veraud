import { NavLink } from "react-router-dom"
import { DropdownLinks, ExternalIcon, GridIcon, ShieldIcon, SlidersIcon, type DropdownLinkItem } from "../../shared/ui-kit/index.ts"
import type { ServiceStatus } from "../useBackendStatus.ts"
import "./AppNavigation.css"

const backendDocsUrl = `${(import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501").replace(/\/+$/, "")}/docs`
const agentServerDocsUrl = `${(import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")}/docs`
const documentationLinks: DropdownLinkItem[] = [
  { label: "Backend docs", href: backendDocsUrl, external: true },
  { label: "WebSocket docs", href: `${backendDocsUrl}/ws`, external: true },
  { label: "Agent-server docs", href: agentServerDocsUrl, external: true },
]

export function AppBrand({ compact = false }: { compact?: boolean }) {
  return <NavLink to="/" className="app-brand" aria-label="Veraud" title="Veraud">
    <ShieldIcon size={18} />
    {!compact && "Veraud"}
  </NavLink>
}

export function AppMainNavigation({ compact = false }: { compact?: boolean }) {
  return <nav className="app-nav" aria-label="Main navigation">
    <NavLink to="/" end aria-label="Home" title="Home" className={({ isActive }) => isActive ? "app-nav-active" : ""}>
      <GridIcon />
      {!compact && "Home"}
    </NavLink>
    <NavLink to="/settings" aria-label="Settings" title="Settings" className={({ isActive }) => isActive ? "app-nav-active" : ""}>
      <SlidersIcon />
      {!compact && "Settings"}
    </NavLink>
  </nav>
}

export function AppDocumentationLinks({ align = "end", compact = false }: { align?: "start" | "end", compact?: boolean }) {
  return <DropdownLinks label="API docs" icon={<ExternalIcon size={14} />} items={documentationLinks} align={align} iconOnly={compact} />
}

function StatusBadge({ label, status, compact }: { label: string, status: ServiceStatus, compact: boolean }) {
  const online = status === "online"
  const unknown = status === "unknown"
  const text = `${label}: ${online ? "Online" : unknown ? "Unknown" : "Offline"}`
  return <span title={text} aria-label={text} className={online ? "app-status" : unknown ? "app-status app-status-unknown" : "app-status app-status-offline"}>
    <span
      className={online ? "app-status-dot" : unknown ? "app-status-dot app-status-dot-unknown" : "app-status-dot app-status-dot-offline"}
      aria-hidden="true"
    />
    {!compact && text}
  </span>
}

/** Presentational only: the containing layout owns the single status poll. */
export function AppServiceIndicators({ backend, agent, compact = false }: { backend: ServiceStatus, agent: ServiceStatus, compact?: boolean }) {
  return <>
    <StatusBadge label="Backend" status={backend} compact={compact} />
    <StatusBadge label="Agents Server" status={agent} compact={compact} />
  </>
}

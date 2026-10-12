import { NavLink, Outlet } from "react-router-dom"
import { DropdownLinks, ExternalIcon, GridIcon, ShieldIcon, SlidersIcon, type DropdownLinkItem } from "../shared/ui-kit/index.ts"
import { Dock } from "./dock.tsx"
import { ToastProvider } from "./toasts.tsx"
import { useBackendStatus, type ServiceStatus } from "./useBackendStatus.ts"
import "./layout.css"

const backendDocsUrl = `${(import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501").replace(/\/+$/, "")}/docs`
const websocketDocsUrl = `${backendDocsUrl}/ws`
const agentServerDocsUrl = `${(import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")}/docs`
const documentationLinks: DropdownLinkItem[] = [
  { label: "Backend docs", href: backendDocsUrl, external: true },
  { label: "WebSocket docs", href: websocketDocsUrl, external: true },
  { label: "Agent-server docs", href: agentServerDocsUrl, external: true },
]

function StatusBadge({ label, status }: { label: string; status: ServiceStatus }) {
  const online = status === "online"
  const unknown = status === "unknown"

  return (
    <span
      className={
        online ? "app-status" : unknown ? "app-status app-status-unknown" : "app-status app-status-offline"
      }
    >
      <span
        className={
          online
            ? "app-status-dot"
            : unknown
              ? "app-status-dot app-status-dot-unknown"
              : "app-status-dot app-status-dot-offline"
        }
        aria-hidden="true"
      />
      {label}: {online ? "Online" : unknown ? "Unknown" : "Offline"}
    </span>
  )
}

export function AppLayout() {
  const { backend, agent } = useBackendStatus()

  return (
    <ToastProvider>
      <div className="app">
        <header className="app-header">
          <NavLink to="/" className="app-brand">
            <ShieldIcon size={18} />
            Veraud
          </NavLink>
          <StatusBadge label="Backend" status={backend} />
          <StatusBadge label="Agents Server" status={agent} />
          <div className="app-header-links">
            <nav className="app-nav" aria-label="Main navigation">
              <NavLink to="/" className={({ isActive }) => (isActive ? "app-nav-active" : "")}>
                <GridIcon />
                Home
              </NavLink>
              <NavLink to="/settings" className={({ isActive }) => (isActive ? "app-nav-active" : "")}>
                <SlidersIcon />
                Settings
              </NavLink>
            </nav>
            <div className="app-docs-nav">
              <DropdownLinks label="API docs" icon={<ExternalIcon size={14} />} items={documentationLinks} align="end" />
            </div>
          </div>
        </header>
        <main className="app-main">
          <Outlet />
        </main>
        <Dock />
      </div>
    </ToastProvider>
  )
}

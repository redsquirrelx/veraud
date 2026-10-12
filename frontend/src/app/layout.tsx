import { NavLink, Outlet } from "react-router-dom"
import { ExternalIcon, GridIcon, ShieldIcon, SlidersIcon } from "../shared/ui-kit/index.ts"
import { Dock } from "./dock.tsx"
import { ToastProvider } from "./toasts.tsx"
import { useBackendStatus, type ServiceStatus } from "./useBackendStatus.ts"
import "./layout.css"

const backendDocsUrl = `${(import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501").replace(/\/+$/, "")}/docs`
const websocketDocsUrl = `${backendDocsUrl}/ws`
const agentServerDocsUrl = `${(import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")}/docs`
const documentationLinks = [
  { label: "Backend docs", url: backendDocsUrl },
  { label: "WebSocket docs", url: websocketDocsUrl },
  { label: "Agent-server docs", url: agentServerDocsUrl },
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
                General settings
              </NavLink>
            </nav>
            <nav className="app-nav app-docs-nav" aria-label="API documentation">
              <span className="app-docs-label">API docs</span>
              {documentationLinks.map(({ label, url }) => (
                <a key={label} href={url} target="_blank" rel="noopener noreferrer" aria-label={`${label} (opens in a new tab)`}>
                  <ExternalIcon size={14} />
                  {label}
                </a>
              ))}
            </nav>
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

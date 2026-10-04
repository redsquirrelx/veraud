import { NavLink, Outlet } from "react-router-dom"
import { GridIcon, ShieldIcon, SlidersIcon } from "../shared/ui-kit/index.ts"
import { useBackendStatus, type ServiceStatus } from "./useBackendStatus.ts"
import "./layout.css"

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
    <div className="app">
      <header className="app-header">
        <NavLink to="/" className="app-brand">
          <ShieldIcon size={18} />
          Veraud
        </NavLink>
        <StatusBadge label="Backend" status={backend} />
        <StatusBadge label="Agents Server" status={agent} />
        <nav className="app-nav">
          <NavLink to="/" className={({ isActive }) => (isActive ? "app-nav-active" : "")}>
            <GridIcon />
            Home
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? "app-nav-active" : "")}>
            <SlidersIcon />
            General settings
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}

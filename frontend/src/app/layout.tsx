import { NavLink, Outlet } from "react-router-dom"
import { GridIcon, ShieldIcon, SlidersIcon } from "../shared/ui-kit/index.ts"
import { useBackendStatus } from "./useBackendStatus.ts"
import "./layout.css"

export function AppLayout() {
  const backendStatus = useBackendStatus()
  const online = backendStatus === "online"

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-brand">
          <ShieldIcon size={18} />
          Veraud
        </span>
        <span className={online ? "app-status" : "app-status app-status-offline"}>
          <span className={online ? "app-status-dot" : "app-status-dot app-status-dot-offline"} aria-hidden="true" />
          {online ? "Online" : "Offline"}
        </span>
        <nav className="app-nav">
          <NavLink to="/" className={({ isActive }) => (isActive ? "app-nav-active" : "")}>
            <GridIcon />
            Home
          </NavLink>
          <span className="app-nav-disabled">
            <SlidersIcon />
            General settings
          </span>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}

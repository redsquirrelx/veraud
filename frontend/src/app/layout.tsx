import { Outlet } from "react-router-dom"
import { Dock } from "./dock.tsx"
import { ToastProvider } from "./toasts.tsx"
import { SettingsProvider } from "./settingsContext.tsx"
import { useBackendStatus } from "./useBackendStatus.ts"
import "./layout.css"

export type AppLayoutContext = ReturnType<typeof useBackendStatus>

export function AppLayout() {
  const services = useBackendStatus()

  return (
    <ToastProvider>
      <div className="app">
        <SettingsProvider>
          <Outlet context={services satisfies AppLayoutContext} />
          <Dock />
        </SettingsProvider>
      </div>
    </ToastProvider>
  )
}

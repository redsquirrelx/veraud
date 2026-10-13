import { Outlet, useOutletContext } from "react-router-dom"
import type { AppLayoutContext } from "./layout.tsx"

/** Project details own their sidebar and contextual version controls. */
export function ProjectLayout() {
  const services = useOutletContext<AppLayoutContext>()
  return <main className="app-main app-project-layout">
    <Outlet context={services} />
  </main>
}

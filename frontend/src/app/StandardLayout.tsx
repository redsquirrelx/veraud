import { Outlet, useOutletContext } from "react-router-dom"
import type { AppLayoutContext } from "./layout.tsx"
import { AppBrand, AppDocumentationLinks, AppMainNavigation, AppServiceIndicators } from "./navigation/AppNavigation.tsx"

/** General pages share the application header. */
export function StandardLayout() {
  const services = useOutletContext<AppLayoutContext>()
  return <>
    <header className="app-header">
      <AppBrand />
      <AppServiceIndicators backend={services.backend} agent={services.agent} />
      <div className="app-header-links">
        <AppMainNavigation />
        <div className="app-docs-nav">
          <AppDocumentationLinks />
        </div>
      </div>
    </header>
    <main className="app-main">
      <Outlet context={services} />
    </main>
  </>
}

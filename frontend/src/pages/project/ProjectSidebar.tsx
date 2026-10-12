import { useOutletContext } from "react-router-dom"
import type { AppLayoutContext } from "../../app/layout.tsx"
import { AppBrand, AppDocumentationLinks, AppMainNavigation, AppServiceIndicators } from "../../app/navigation/AppNavigation.tsx"
import { Sidebar, type SidebarItem } from "../../shared/ui-kit/Sidebar.tsx"
import "./ProjectSidebar.css"

export function ProjectSidebar({ items, activeId, onSelect }: { items: SidebarItem[], activeId: string, onSelect: (id: string) => void }) {
  const services = useOutletContext<AppLayoutContext | undefined>()
  return <Sidebar title="Project" items={items} activeId={activeId} onSelect={onSelect} storageKey="sidebar.expanded"
    header={(expanded) => <AppBrand compact={!expanded} />}
    beforeItems={(expanded) => <div className="project-sidebar-navigation">
      <AppMainNavigation compact={!expanded} />
      {expanded && <span className="project-sidebar-section-title">Project</span>}
    </div>}
    footer={(expanded) => <div className="project-sidebar-footer">
      <AppDocumentationLinks align="start" compact={!expanded} />
      <div className="project-sidebar-services" role="group" aria-label="Service status">
        <AppServiceIndicators backend={services?.backend ?? "unknown"} agent={services?.agent ?? "unknown"} compact={!expanded} />
      </div>
    </div>}
  />
}

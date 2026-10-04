import { useState } from "react"
import { Button, Card, FolderIcon, Sidebar, TextInput, Toast } from "../../shared/ui-kit/index.ts"
import "./TestSidebarPage.css"

const menuItems = [
  { id: "projects", label: "Projects", icon: <FolderIcon /> },
  { id: "audits", label: "Audits", icon: <FolderIcon /> },
  { id: "reports", label: "Reports", icon: <FolderIcon /> },
]

export function TestSidebarPage() {
  const [active, setActive] = useState("projects")

  return (
    <section className="test-sidebar-page">
      <Sidebar title="Workspace" items={menuItems} activeId={active} storageKey="sidebar.expanded" onSelect={setActive} />
      <div className="test-sidebar-content">
        <h1>Sidebar playground</h1>
        <Card>
          <span className="label">Active section</span>
          <p className="mono">{active}</p>
        </Card>
        <div className="test-sidebar-row">
          <TextInput value="" placeholder="Search in section" onChange={() => {}} />
          <Button>Apply</Button>
        </div>
        <Toast kind="success" message="Sidebar is ready" />
      </div>
    </section>
  )
}

import { useState } from "react"
import { Link } from "react-router-dom"
import { Card, DropdownMenu, type DropdownMenuItem } from "../../shared/ui-kit/index.ts"
import "./TestDropdownPage.css"

const pipelineItems: DropdownMenuItem[] = [
  { id: "architecture-audit", label: "Classic audit", description: "Analyzer then architect" },
  { id: "project-architecture", label: "Project architecture", description: "Orientation, architecture and semantic validation" },
  { id: "coming-soon", label: "Coming soon", description: "Not available yet", disabled: true },
]

export function TestDropdownPage() {
  const [selectedId, setSelectedId] = useState<string | null>("architecture-audit")
  const [lastChosen, setLastChosen] = useState<string | null>(null)

  return (
    <section className="test-dropdown-page">
      <h1>Dropdown playground</h1>
      <p className="label">
        <Link to="/test">All playgrounds</Link>
      </p>
      <Card>
        <span className="label">Action menu with a selected option</span>
        <DropdownMenu
          label="Analyze"
          items={pipelineItems}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id)
            setLastChosen(id)
          }}
        />
      </Card>
      <Card>
        <span className="label">Last chosen option</span>
        <p className="mono">{lastChosen ?? "none"}</p>
      </Card>
      <Card>
        <span className="label">Loading trigger</span>
        <DropdownMenu label="Analyze" items={pipelineItems} loading loadingText="Analyzing" onSelect={() => {}} />
      </Card>
      <Card>
        <span className="label">Disabled trigger and empty menu</span>
        <div className="test-dropdown-row">
          <DropdownMenu label="Disabled" items={pipelineItems} disabled onSelect={() => {}} />
          <DropdownMenu label="Empty" items={[]} emptyText="No pipelines registered" onSelect={() => {}} />
        </div>
      </Card>
    </section>
  )
}

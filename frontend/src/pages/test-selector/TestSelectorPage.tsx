import { useState } from "react"
import { Card, ItemSearcher, ItemSelector, type ItemSelectorItem } from "../../shared/ui-kit/index.ts"
import "./TestSelectorPage.css"

const PAGE_SIZE = 10

const allBranches: ItemSelectorItem[] = Array.from({ length: 25 }, (_, index) => {
  if (index === 0) {
    return { id: "main", label: "main", detail: "default branch" }
  }
  return { id: `feature-${index}`, label: `feature-${index}`, detail: `${index} commits ahead` }
})

export function TestSelectorPage() {
  const [visible, setVisible] = useState(PAGE_SIZE)
  const [selectedId, setSelectedId] = useState<string | null>("main")
  const [foundId, setFoundId] = useState<string | null>(null)
  const items = allBranches.slice(0, visible)

  function loadMore() {
    setVisible((count) => Math.min(count + PAGE_SIZE, allBranches.length))
  }

  return (
    <section className="test-selector-page">
      <h1>Selector playground</h1>
      <Card>
        <span className="label">Branches ({items.length} of {allBranches.length})</span>
        <ItemSelector
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          hasMore={visible < allBranches.length}
          onLoadMore={loadMore}
        />
      </Card>
      <Card>
        <span className="label">Selected branch</span>
        <p className="mono">{selectedId ?? "none"}</p>
      </Card>
      <Card>
        <span className="label">Find a branch by id</span>
        <ItemSearcher
          items={items}
          selectedId={foundId}
          onSelect={setFoundId}
          hasMore={visible < allBranches.length}
          onLoadMore={loadMore}
        />
      </Card>
      <Card>
        <span className="label">Found branch</span>
        <p className="mono">{foundId ?? "none"}</p>
      </Card>
    </section>
  )
}

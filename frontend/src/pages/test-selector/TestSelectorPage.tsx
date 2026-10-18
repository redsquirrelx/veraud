import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Card, ItemSearcher, ItemSelector } from "../../shared/ui-kit/index.ts"
import "./TestSelectorPage.css"

const PAGE_SIZE = 10
const BRANCH_COUNT = 25

export function TestSelectorPage() {
  const { t } = useTranslation("common")
  const allBranches = Array.from({ length: BRANCH_COUNT }, (_, index) => {
    if (index === 0) {
      return { id: "main", label: "main", detail: t("testPages.selector.branchDefault") }
    }
    return { id: `feature-${index}`, label: `feature-${index}`, detail: t("testPages.selector.commitsAhead", { count: index }) }
  })
  const [visible, setVisible] = useState(PAGE_SIZE)
  const [selectedId, setSelectedId] = useState<string | null>("main")
  const [foundId, setFoundId] = useState<string | null>(null)
  const items = allBranches.slice(0, visible)

  function loadMore() {
    setVisible((count) => Math.min(count + PAGE_SIZE, allBranches.length))
  }

  return (
    <section className="test-selector-page">
      <h1>{t("testPages.selector.title")}</h1>
      <Card>
        <span className="label">{t("testPages.selector.branches", { visible: items.length, total: allBranches.length })}</span>
        <ItemSelector
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          hasMore={visible < allBranches.length}
          onLoadMore={loadMore}
        />
      </Card>
      <Card>
        <span className="label">{t("testPages.selector.selectedBranch")}</span>
        <p className="mono">{selectedId ?? t("testPages.none")}</p>
      </Card>
      <Card>
        <span className="label">{t("testPages.selector.findById")}</span>
        <ItemSearcher
          items={items}
          selectedId={foundId}
          onSelect={setFoundId}
          hasMore={visible < allBranches.length}
          onLoadMore={loadMore}
        />
      </Card>
      <Card>
        <span className="label">{t("testPages.selector.foundBranch")}</span>
        <p className="mono">{foundId ?? t("testPages.none")}</p>
      </Card>
    </section>
  )
}

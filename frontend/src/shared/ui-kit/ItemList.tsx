import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"
import "./ItemList.css"

export interface ItemListEntry {
  id: string
  name: string
  description?: string
}

interface ItemListProps {
  items: ItemListEntry[]
  selectedIds: string[]
  onSelectionChange: (selectedIds: string[]) => void
  mode?: "single" | "multiple"
  loading?: boolean
  renderItem?: (item: ItemListEntry, selected: boolean) => ReactNode
  emptyText?: string
}

export function ItemList({ items, selectedIds, onSelectionChange, mode = "multiple", loading = false, renderItem = defaultRender, emptyText }: ItemListProps) {
  const { t } = useTranslation("common")
  const resolvedEmptyText = emptyText ?? t("ui.itemList.empty")
  if (loading && items.length === 0) {
    return (
      <ul className="ui-item-list-rows" aria-label={t("ui.itemList.items")} aria-busy="true">
        {[0, 1, 2].map((index) => (
          <li key={index} className="ui-item-list-skeleton" aria-hidden="true" />
        ))}
      </ul>
    )
  }

  if (items.length === 0) {
    return <p className="label">{resolvedEmptyText}</p>
  }

  function pick(id: string) {
    if (mode === "single") {
      onSelectionChange(selectedIds.includes(id) ? [] : [id])
      return
    }
    onSelectionChange(selectedIds.includes(id) ? selectedIds.filter((entry) => entry !== id) : [...selectedIds, id])
  }

  return (
    <ul className="ui-item-list-rows" role="listbox" aria-label={t("ui.itemList.items")} aria-multiselectable={mode === "multiple"}>
      {items.map((item) => {
        const selected = selectedIds.includes(item.id)
        return (
          <li key={item.id}>
            <div
              role="option"
              tabIndex={0}
              aria-selected={selected}
              className={selected ? "ui-item-list-row ui-item-list-active" : "ui-item-list-row"}
              onClick={() => pick(item.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  pick(item.id)
                }
              }}
            >
              {renderItem(item, selected)}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function ItemListItem({ name, description }: { name: string, description?: string }) {
  return (
    <>
      <span className="mono">{name}</span>
      {description !== undefined && description !== "" && <span className="label">{description}</span>}
    </>
  )
}

function defaultRender(item: ItemListEntry): ReactNode {
  return <ItemListItem name={item.name} description={item.description} />
}

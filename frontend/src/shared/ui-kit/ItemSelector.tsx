import { useEffect, useRef, useState } from "react"
import { ChevronDownIcon, ChevronUpIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import "./ItemSelector.css"

export interface ItemSelectorItem {
  id: string
  label: string
  detail?: string
}

interface ItemSelectorProps {
  items: ItemSelectorItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  hasMore: boolean
  loadingMore?: boolean
  onLoadMore: () => void
  emptyText?: string
  loadMoreText?: string
  placeholder?: string
  label?: string
  loading?: boolean
  onOpen?: () => void
}

export function ItemSelector({
  items,
  selectedId,
  onSelect,
  hasMore,
  loadingMore = false,
  onLoadMore,
  emptyText = "No items yet",
  loadMoreText = "Load more...",
  placeholder = "Select an item",
  label = "",
  loading = false,
  onOpen,
}: ItemSelectorProps) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement | null>(null)
  const selected = items.find((item) => item.id === selectedId) ?? null

  useEffect(() => {
    function handlePointer(event: MouseEvent) {
      if (root.current !== null && !root.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handlePointer)
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("mousedown", handlePointer)
      document.removeEventListener("keydown", handleKey)
    }
  }, [])

  function pick(id: string) {
    onSelect(id)
    setOpen(false)
  }

  function toggle() {
    if (loading) {
      return
    }
    if (!open) {
      onOpen?.()
    }
    setOpen(!open)
  }

  return (
    <div className="ui-item-selector" ref={root}>
      {label !== "" && <span className="ui-item-legend">{label}</span>}
      <button
        type="button"
        className="ui-item-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={loading}
        onClick={toggle}
      >
        {loading ? (
          <span className="ui-item-loading">
            <Spinner size={12} />
            <span>Loading</span>
          </span>
        ) : (
          <>
            <span className={selected === null ? "ui-item-placeholder" : "mono"}>{selected?.label ?? placeholder}</span>
            {open ? <ChevronUpIcon /> : <ChevronDownIcon />}
          </>
        )}
      </button>
      <div className={open ? "ui-item-panel ui-item-panel-open" : "ui-item-panel"} aria-hidden={!open} inert={!open}>
        {items.length === 0 && !hasMore ? (
          <p className="label">{emptyText}</p>
        ) : (
          <ul className="ui-item-list" role="listbox" aria-label="Items">
            {items.map((item) => (
              <li key={item.id} className="ui-item-enter">
                <button
                  type="button"
                  role="option"
                  aria-selected={item.id === selectedId}
                  className={item.id === selectedId ? "ui-item ui-item-active" : "ui-item"}
                  onClick={() => pick(item.id)}
                >
                  <span className="mono">{item.label}</span>
                  {item.detail !== undefined && item.detail !== "" && <span className="label">{item.detail}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
        {hasMore && (
          <button
            type="button"
            className="ui-item-more"
            disabled={loadingMore}
            onClick={onLoadMore}
          >
            {loadingMore ? "Loading" : loadMoreText}
          </button>
        )}
      </div>
    </div>
  )
}

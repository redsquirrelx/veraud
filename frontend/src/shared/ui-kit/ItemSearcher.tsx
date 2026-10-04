import { useEffect, useMemo, useRef, useState, type FocusEvent } from "react"
import { ChevronDownIcon, ChevronUpIcon, XIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import type { ItemSelectorItem } from "./ItemSelector.tsx"
import "./ItemSearcher.css"

interface ItemSearcherProps {
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
  disabled?: boolean
}

export function ItemSearcher({
  items,
  selectedId,
  onSelect,
  hasMore,
  loadingMore = false,
  onLoadMore,
  emptyText = "No matches",
  loadMoreText = "Load more...",
  placeholder = "Type an id to select it directly",
  label = "",
  loading = false,
  disabled = false,
}: ItemSearcherProps) {
  const selected = items.find((item) => item.id === selectedId) ?? null
  const [text, setText] = useState(selected?.label ?? selectedId ?? "")
  const [open, setOpen] = useState(false)
  const [filtering, setFiltering] = useState(false)
  const root = useRef<HTMLDivElement | null>(null)
  const field = useRef<HTMLInputElement | null>(null)

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

  const query = text.trim().toLowerCase()
  const visible = useMemo(() => {
    if (filtering === false || query === "") {
      return items
    }
    return items.filter((item) => item.id.toLowerCase().includes(query) || item.label.toLowerCase().includes(query))
  }, [items, query, filtering])

  function pick(id: string) {
    const match = items.find((item) => item.id === id) ?? null
    setText(match?.label ?? id)
    setFiltering(false)
    setOpen(false)
    onSelect(id)
  }

  function commitText() {
    const wanted = text.trim()
    if (wanted === "") {
      return
    }
    const exact = items.find((item) => item.id.toLowerCase() === wanted.toLowerCase()) ?? null
    pick(exact?.id ?? wanted)
  }

  function clearText() {
    setText("")
    setFiltering(false)
    setOpen(true)
    field.current?.focus()
  }

  if (loading) {
    return (
      <div className="ui-item-searcher" ref={root}>
        {label !== "" && <span className="ui-item-legend">{label}</span>}
        <button type="button" className="ui-item-button" disabled>
          <span className="ui-item-loading">
            <Spinner size={12} />
            <span>Loading</span>
          </span>
        </button>
      </div>
    )
  }

  function commitOnBlur(event: FocusEvent<HTMLInputElement>) {
    const next = event.relatedTarget as Node | null
    if (next !== null && root.current?.contains(next)) {
      return
    }
    const wanted = text.trim()
    if (wanted !== "") {
      pick(wanted)
    }
  }

  return (
    <div className="ui-item-searcher" ref={root}>
      {label !== "" && <span className="ui-item-legend">{label}</span>}
      <div className="ui-item-search-row">
        <div className="ui-item-search-field">
          <input
            type="text"
            ref={field}
            className="ui-input ui-item-search-input"
            value={text}
            placeholder={placeholder}
            aria-label="Search items"
            disabled={disabled}
            onChange={(event) => {
              setText(event.target.value)
              setFiltering(true)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onBlur={commitOnBlur}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                commitText()
              }
            }}
          />
          {text !== "" && !disabled && (
            <button
              type="button"
              className="ui-item-clear"
              aria-label="Clear search"
              onClick={clearText}
            >
              <XIcon size={12} />
            </button>
          )}
        </div>
        <button
          type="button"
          className="ui-item-search-toggle"
          aria-label={open ? "Close items" : "Open items"}
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <ChevronUpIcon /> : <ChevronDownIcon />}
        </button>
      </div>
      <div className={open ? "ui-item-panel ui-item-panel-open" : "ui-item-panel"} aria-hidden={!open} inert={!open}>
        {loading && visible.length === 0 && !hasMore ? (
          <span className="ui-item-loading">
            <Spinner size={12} />
            <span className="label">Loading</span>
          </span>
        ) : visible.length === 0 && !hasMore ? (
          <p className="label">{emptyText}</p>
        ) : (
          <ul className="ui-item-list" role="listbox" aria-label="Items">
            {visible.map((item) => (
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

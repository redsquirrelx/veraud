import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { ChevronDownIcon, ChevronRightIcon, DotsIcon, FolderIcon } from "./icons.tsx"
import { ItemSelector } from "./ItemSelector.tsx"
import { Panel } from "./Panel.tsx"
import { RefreshButton } from "./RefreshButton.tsx"
import { TextInput } from "./TextInput.tsx"
import {
  ALL_EXTENSIONS,
  activeGroupsOf,
  breadcrumbOf,
  flattenDirectory,
  groupOf,
  isFiltering,
  listExtensions,
  matchRows,
  rowClassName,
  visibleRows,
  type DirectoryGroup,
  type DirectoryTreeNode,
  type DirectoryTreeRow,
} from "./directoryTree.ts"
import "./DirectoryTree.css"

interface DirectoryTreeProps {
  tree: DirectoryTreeNode
  groups?: DirectoryGroup[]
  flaggedPaths?: string[]
  initialSelected?: string | null
  initialExpanded?: string[]
  onRefresh?: () => Promise<void> | void
  onSelectFile?: (path: string) => void
}

interface DirectoryTreeItemProps {
  row: DirectoryTreeRow
  isSelected: boolean
  isFlagged: boolean
  isOpen: boolean
  group: DirectoryGroup | null
  onToggle: (path: string) => void
  onSelect: (path: string) => void
}

export function DirectoryTree({
  tree,
  groups = [],
  flaggedPaths = [],
  initialSelected = null,
  initialExpanded = [],
  onRefresh,
  onSelectFile,
}: DirectoryTreeProps) {
  const [expanded, setExpanded] = useState<string[]>([tree.name, ...initialExpanded])
  const [selected, setSelected] = useState<string | null>(initialSelected)
  const [nameFilter, setNameFilter] = useState("")
  const [extension, setExtension] = useState(ALL_EXTENSIONS)
  const [refreshing, setRefreshing] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const filtersRef = useRef<HTMLDivElement | null>(null)

  const rows = useMemo(() => flattenDirectory(tree), [tree])
  const flagged = useMemo(() => new Set(flaggedPaths), [flaggedPaths])
  const activeGroups = useMemo(() => activeGroupsOf(rows, groups), [rows, groups])
  const extensions = useMemo(() => listExtensions(rows), [rows])
  const query = nameFilter.trim().toLowerCase()
  const match = useMemo(
    () => isFiltering({ query, extension }) ? matchRows(rows, { query, extension }) : null,
    [rows, query, extension]
  )

  const isOpen = useCallback(
    (path: string) => expanded.includes(path) || (match !== null && match.forced.has(path)),
    [expanded, match]
  )
  const visible = useMemo(() => visibleRows(rows, match, isOpen), [rows, match, isOpen])
  const breadcrumb = breadcrumbOf(selected)

  function toggle(path: string) {
    setExpanded((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path])
  }

  function selectFile(path: string) {
    setSelected(path)
    onSelectFile?.(path)
  }

  function resetFilters() {
    setNameFilter("")
    setExtension(ALL_EXTENSIONS)
  }

  // Closes the overflow menu on outside click or Escape. The menu itself is
  // driven by a container query in CSS, so this only handles dismissal.
  useEffect(() => {
    if (!menuOpen) {
      return
    }
    function handlePointer(event: MouseEvent) {
      if (filtersRef.current !== null && !filtersRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handlePointer)
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("mousedown", handlePointer)
      document.removeEventListener("keydown", handleKey)
    }
  }, [menuOpen])

  async function refresh() {
    if (refreshing || onRefresh === undefined) {
      return
    }
    setRefreshing(true)

    try {
      await onRefresh()
    } catch {
      // the caller owns its own error reporting; we only guarantee the UI unlocks
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="directory-tree-view" aria-busy={refreshing}>
      <Panel>
        <div className="directory-filters" ref={filtersRef}>
          <span className="label">Filter</span>
          <TextInput value={nameFilter} placeholder="File or folder name" disabled={refreshing} onChange={setNameFilter} />
          <span className="label">Extension</span>
          <ItemSelector
            items={[
              { id: ALL_EXTENSIONS, label: "All" },
              ...extensions.map((value) => ({ id: value, label: value })),
            ]}
            selectedId={extension}
            onSelect={setExtension}
            hasMore={false}
            onLoadMore={() => {}}
            emptyText="No extensions"
            placeholder="All"
            disabled={refreshing}
          />
          {visible.length === 0 ? (
            <button type="button" className="directory-reset" onClick={resetFilters}>Clear</button>
          ) : (
            <span className="label">{visible.length} of {rows.length}</span>
          )}
          {onRefresh !== undefined && <RefreshButton loading={refreshing} onClick={() => void refresh()} />}
          <button
            type="button"
            className="directory-overflow"
            aria-label="More filters"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((value) => !value)}
          >
            <DotsIcon size={14} />
          </button>
          {menuOpen && (
            <div className="directory-overflow-panel" role="menu" aria-label="More filters">
              <span className="label">Filter</span>
              <TextInput value={nameFilter} placeholder="File or folder name" disabled={refreshing} onChange={setNameFilter} />
              <span className="label">Extension</span>
              <ItemSelector
                items={[
                  { id: ALL_EXTENSIONS, label: "All" },
                  ...extensions.map((value) => ({ id: value, label: value })),
                ]}
                selectedId={extension}
                onSelect={setExtension}
                hasMore={false}
                onLoadMore={() => {}}
                emptyText="No extensions"
                placeholder="All"
                disabled={refreshing}
              />
              {onRefresh !== undefined && <RefreshButton loading={refreshing} onClick={() => void refresh()} />}
            </div>
          )}
        </div>
      </Panel>
      <nav className="directory-breadcrumbs" aria-label="Breadcrumb">
        {breadcrumb.length === 0 ? (
          <span className="label">No file selected</span>
        ) : (
          breadcrumb.map((part, index) => (
            <span key={part} className="directory-crumb">
              {index > 0 && <ChevronRightIcon size={11} />}
              <span className={index === breadcrumb.length - 1 ? "mono" : "label"}>{part}</span>
            </span>
          ))
        )}
      </nav>
      {visible.length === 0 ? (
        <p className="label directory-empty">No entries match the filter</p>
      ) : (
        <ul className="directory-tree" role="tree">
          {visible.map((row) => (
            <DirectoryTreeItem
              key={row.path}
              row={row}
              isSelected={row.path === selected}
              isFlagged={flagged.has(row.path)}
              isOpen={isOpen(row.path)}
              group={groupOf(activeGroups, row.path)}
              onToggle={toggle}
              onSelect={selectFile}
            />
          ))}
        </ul>
      )}
      {activeGroups.length > 0 && (
        <div className="directory-legend">
          {activeGroups.map((group) => (
            <span key={group.id} className={`directory-tag directory-tag-${group.tone}`}>{group.label}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function DirectoryTreeItem({ row, isSelected, isFlagged, isOpen, group, onToggle, onSelect }: DirectoryTreeItemProps) {
  return (
    <li
      role="treeitem"
      aria-selected={isSelected}
      aria-expanded={row.isFolder ? isOpen : undefined}
    >
      <button
        type="button"
        className={rowClassName(isSelected, isFlagged, group)}
        style={{ paddingLeft: `${row.depth * 16 + 8}px` }}
        onClick={() => row.isFolder ? onToggle(row.path) : onSelect(row.path)}
      >
        {row.isFolder
          ? isOpen
            ? <ChevronDownIcon size={12} />
            : <ChevronRightIcon size={12} />
          : <span className="directory-spacer" />}
        {row.isFolder && <FolderIcon size={14} />}
        <span className="mono">{row.name}</span>
        <span className="directory-tags">
          {group !== null && (
            <span className={`directory-tag directory-tag-${group.tone}`}>{group.label}</span>
          )}
          {isFlagged && <span className="directory-tag directory-tag-flagged">flagged</span>}
        </span>
      </button>
    </li>
  )
}

import { useCallback, useMemo, useState } from "react"
import { ChevronDownIcon, ChevronRightIcon, FolderIcon } from "./icons.tsx"
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
}: DirectoryTreeProps) {
  const [expanded, setExpanded] = useState<string[]>([tree.name, ...initialExpanded])
  const [selected, setSelected] = useState<string | null>(initialSelected)
  const [nameFilter, setNameFilter] = useState("")
  const [extension, setExtension] = useState(ALL_EXTENSIONS)
  const [refreshing, setRefreshing] = useState(false)

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

  function resetFilters() {
    setNameFilter("")
    setExtension(ALL_EXTENSIONS)
  }

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
        <div className="directory-filters">
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
              onSelect={setSelected}
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

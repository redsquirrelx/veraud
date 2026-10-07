# Frontend Contract — DirectoryTree

Dumb, reusable tree of a repository checkout. It renders a `tree` prop,
lets the auditor pick a file, colour directories by group and flag the
paths an audit pointed at. No fetching, no persistence, no backend calls:
the caller owns the data and passes it in.

Source of truth: `frontend/src/shared/ui-kit/DirectoryTree.tsx`
(render), `directoryTree.ts` (pure logic + types),
`DirectoryTree.css` (styling contract).
Playground: `/test/directory`.

## Import

```tsx
import { DirectoryTree, type DirectoryGroup, type DirectoryTreeNode } from "../../shared/ui-kit/index.ts"
```

## Props

| Prop | Type | Default | Meaning |
|---|---|---|---|
| `tree` | `DirectoryTreeNode` | required | Root folder. `{ name: string, children?: DirectoryTreeNode[] }`. A node without `children` is a file. |
| `groups` | `DirectoryGroup[]` | `[]` | Colour buckets: `{ id: string, label: string, tone: DirectoryGroupTone, paths: string[] }`. `tone` is `success` \| `warning` \| `info` \| `danger`. |
| `flaggedPaths` | `string[]` | `[]` | Full paths that carry the `flagged` badge. |
| `initialSelected` | `string \| null` | `null` | Path selected on first render only. |
| `initialExpanded` | `string[]` | `[]` | Extra folders opened on first render; the root is always open. |
| `onRefresh` | `() => Promise<void> \| void` | — | When present, a `RefreshButton` appears. The button is hidden without it. |
| `onSelectFile` | `(path: string) => void` | — | Called with the full path when a file is picked. Folders never notify. |

Paths are always **absolute inside the tree**, slash separated and
without a leading slash: `"payment-gateway-v2/src/modules/engine.ts"`,
i.e. the root's own name is the first segment.

## Example

```tsx
const groups: DirectoryGroup[] = [
  { id: "money", label: "critical", tone: "danger", paths: ["payment-gateway-v2/src/modules/reconciliation"] },
  { id: "infra", label: "infrastructure", tone: "info", paths: ["payment-gateway-v2/src/server.ts"] },
]

<DirectoryTree
  tree={tree}
  groups={groups}
  flaggedPaths={["payment-gateway-v2/src/modules/reconciliation/engine.ts"]}
  initialExpanded={["payment-gateway-v2/src"]}
  initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
  onRefresh={async () => { await reload() }}
/>
```

## Internal state

`expanded` (string array), `selected` (path or null), `nameFilter`
(string), `extension` (string, `""` means all) and `refreshing`
(boolean). Only the root, the explicit `initialExpanded` entries and
folders the user clicks are open; `initial*` props are read on mount
only, so changing them later does nothing.

## Behaviour

- **Selection**: clicking a file selects it, updates the breadcrumb
  and fires `onSelectFile` (top); clicking a folder only toggles it.
  `aria-selected` marks the chosen row. The breadcrumb bar keeps a fixed
  `20px` height so the tree below never shifts when the selection (and
  its text length) changes.
- **Groups**: a path takes the colour of the **first** group that lists
  it; a path in two groups is coloured once. A group whose `paths` match
  nothing in the tree is dropped, including from the legend, so the
  legend can never advertise a colour that is not on screen.
- **Legend**: rendered **below** the tree, only when at least one group
  survives the rule above. Single row with horizontal scroll, so the
  column height never changes.
- **Flags**: `flaggedPaths` is orthogonal to groups. A row can be
  `critical` **and** `flagged`. Ungrouped flagged rows get the amber
  tint; a grouped flagged row keeps the group colour and only its left
  stripe turns dark amber, so both signals stay readable.
- **Filter by name**: substring, case-insensitive, on files *and*
  folders. Compact single row (`nowrap`): the input shrinks instead of
  wrapping, so the toolbar height is constant.
- **Filter by extension**: single-select, options are derived from the
  tree (files only, lowercased, unique, sorted). Files without an
  extension never match a specific extension. Query and extension
  combine with AND.
- **Filtering keeps context**: a match is shown with its ancestors, and
  those ancestors auto-open *only while a filter is active*, so a
  collapsed folder cannot hide a match. Clearing the filters restores
  the previous collapse state untouched.
- **Empty**: `No entries match the filter` plus a `Clear` button that
  appears in the toolbar instead of the `visible of total` counter.
- **Overflow**: below `460px` of column width (container query, so no
  measurement loops) the inline controls hide and a "···" button
  (`DotsIcon`, `aria-label="More filters"`) opens the same filter,
  extension and refresh controls stacked in a dropdown. It closes on
  outside click or `Escape`. Every toolbar row is `nowrap` with fixed
  heights, so narrowing the pane never moves the tree vertically.
- **Refresh**: awaits `onRefresh`, shows a spinner, disables the filter
  inputs and marks the root `aria-busy`. Filters, expansion and
  selection survive the reload. Rejections are swallowed on purpose:
  the caller reports its own errors, the component only guarantees the
  UI unlocks.

## Styling contract

Classes the component relies on, in case you need to restyle:
`directory-tree-view`, `directory-legend`, `directory-filters`,
`directory-reset`, `directory-breadcrumbs`, `directory-crumb`,
`directory-tree`, `directory-empty`, `directory-row` plus the optional
`directory-row-group-{tone}`, `directory-row-active`,
`directory-row-flagged`, and the badges `directory-tags` (wrapper),
`directory-tag`, `directory-tag-{tone}`, `directory-tag-flagged`.
`directory-spacer` keeps file rows aligned with folder rows.

The list and the empty placeholder are both a fixed `320px` tall
(`overflow-y: auto` on the list); override in CSS if you need another
height and change both to keep the layout from jumping.

## Accessibility

`role="tree"` on the list, `role="treeitem"` on each row with
`aria-selected` and `aria-expanded` (folders only),
`aria-busy` on the root while reloading, `aria-label="Breadcrumb"` on
the navigation. Icons are decorative SVGs; every control carries a
label.

Out of scope: file contents, fetching, multi-select, marking from the
UI (the caller owns the flagged list) and per-path group inheritance
(colours do not spread to children).

## Pure helpers

`directoryTree.ts` holds the logic with no JSX, so it can be unit tested
or reused by other views: `extensionOf`, `flattenDirectory`,
`treeFromPaths`, `listExtensions`, `activeGroupsOf`, `isFiltering`,
`matchRows`, `visibleRows`, `groupOf`, `rowClassName` and
`breadcrumbOf`, plus the `ALL_EXTENSIONS` sentinel (`""` means "every
extension"). Types: `DirectoryTreeNode`, `DirectoryTreeRow`,
`DirectoryGroup`, `DirectoryGroupTone`, `DirectoryFilter`,
`DirectoryMatch`. All of them are re-exported from
`shared/ui-kit/index.ts`.

`treeFromPaths(root, paths)` is the bridge from a flat backend list to
the tree: it nests the paths under `root`, merges a folder that also
appeared as a file, ignores blank/`.`/trailing segments and sorts
folders before files (ASCII order, so the result is deterministic).

## Used by the project detail

`useProjectTree(projectId, rootName)` (`features/project-management`)
wraps the dumb component for the Files section of `/projects/:id`. It
owns nothing but the in-memory tree: it fetches on demand only, keys
the state by `projectId:rootName` so the tree of another project is
never shown, and releases everything when the page unmounts. The page
is the single driver, refetching when the section is entered, after a
sync, and whenever the selected version changes.

Contract: `POST /api/projects/:id/git/tree` → `files` (paths at
`HEAD`) + `taskId`. Backend spec in
`docs/backend/project-branches.md`.

export interface DirectoryTreeNode {
  name: string
  children?: DirectoryTreeNode[]
}

export interface DirectoryTreeRow {
  path: string
  name: string
  depth: number
  isFolder: boolean
  parents: string[]
}

export type DirectoryGroupTone = "success" | "warning" | "info" | "danger"

export interface DirectoryGroup {
  id: string
  label: string
  tone: DirectoryGroupTone
  paths: string[]
}

export interface DirectoryFilter {
  query: string
  extension: string
}

export interface DirectoryMatch {
  shown: Set<string>
  forced: Set<string>
}

export const ALL_EXTENSIONS = ""

export function extensionOf(name: string): string {  const dot = name.lastIndexOf(".")
  return dot > 0 ? name.slice(dot).toLowerCase() : ""
}

export function flattenDirectory(
  node: DirectoryTreeNode,
  prefix = "",
  depth = 0,
  parents: string[] = [],
  out: DirectoryTreeRow[] = []
): DirectoryTreeRow[] {
  const path = prefix === "" ? node.name : `${prefix}/${node.name}`
  const isFolder = node.children !== undefined && node.children.length > 0
  out.push({ path, name: node.name, depth, isFolder, parents })

  if (node.children === undefined) {
    return out
  }

  for (const child of node.children) {
    flattenDirectory(child, path, depth + 1, [...parents, path], out)
  }

  return out
}

export function listExtensions(rows: DirectoryTreeRow[]): string[] {
  const found = new Set<string>()

  for (const row of rows) {
    if (row.isFolder) {
      continue
    }
    const extension = extensionOf(row.name)
    if (extension !== "") {
      found.add(extension)
    }
  }

  return [...found].sort()
}

export function activeGroupsOf(rows: DirectoryTreeRow[], groups: DirectoryGroup[]): DirectoryGroup[] {
  const known = new Set(rows.map((row) => row.path))
  return groups.filter((group) => group.paths.some((path) => known.has(path)))
}

export function isFiltering(filter: DirectoryFilter): boolean {
  return filter.query !== "" || filter.extension !== ALL_EXTENSIONS
}

export function matchRows(rows: DirectoryTreeRow[], filter: DirectoryFilter): DirectoryMatch {
  const shown = new Set<string>()
  const forced = new Set<string>()

  for (const row of rows) {
    const nameOk = filter.query === "" || row.name.toLowerCase().includes(filter.query)
    const extensionOk = filter.extension === ALL_EXTENSIONS || (!row.isFolder && extensionOf(row.name) === filter.extension)

    if (nameOk === false || extensionOk === false) {
      continue
    }

    shown.add(row.path)

    for (const parent of row.parents) {
      shown.add(parent)
      forced.add(parent)
    }
  }

  return { shown, forced }
}

export function visibleRows(
  rows: DirectoryTreeRow[],
  match: DirectoryMatch | null,
  isOpen: (path: string) => boolean
): DirectoryTreeRow[] {
  return rows.filter((row) => (match === null || match.shown.has(row.path)) && row.parents.every(isOpen))
}

export function groupOf(groups: DirectoryGroup[], path: string): DirectoryGroup | null {
  return groups.find((group) => group.paths.includes(path)) ?? null
}

export function rowClassName(isSelected: boolean, isFlagged: boolean, group: DirectoryGroup | null): string {
  const classes = ["directory-row"]

  if (group !== null) {
    classes.push(`directory-row-group-${group.tone}`)
  }

  if (isSelected) {
    classes.push("directory-row-active")
  }

  if (isFlagged) {
    classes.push("directory-row-flagged")
  }

  return classes.join(" ")
}

export function breadcrumbOf(selected: string | null): string[] {
  return selected === null ? [] : selected.split("/")
}

function sortTree(node: DirectoryTreeNode): void {
  if (node.children === undefined) {
    return
  }

  node.children.sort((left, right) => {
    const leftFolder = left.children !== undefined && left.children.length > 0
    const rightFolder = right.children !== undefined && right.children.length > 0

    if (leftFolder !== rightFolder) {
      return leftFolder ? -1 : 1
    }

    return compareNames(left.name, right.name)
  })

  for (const child of node.children) {
    sortTree(child)
  }
}

function compareNames(left: string, right: string): number {
  if (left === right) {
    return 0
  }
  return left < right ? -1 : 1
}

export function treeFromPaths(root: string, paths: string[]): DirectoryTreeNode {
  const node: DirectoryTreeNode = { name: root, children: [] }

  for (const path of paths) {
    const segments = path.split("/").filter((segment) => segment !== "" && segment !== ".")
    let current = node

    segments.forEach((segment, index) => {
      const isLeaf = index === segments.length - 1
      let child = current.children?.find((candidate) => candidate.name === segment)

      if (child === undefined) {
        child = isLeaf ? { name: segment } : { name: segment, children: [] }
        current.children?.push(child)
      }

      if (isLeaf === false) {
        child.children ??= []
      }

      current = child
    })
  }

  sortTree(node)
  return node
}

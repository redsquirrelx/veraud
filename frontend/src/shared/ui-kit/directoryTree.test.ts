import { describe, expect, it } from "vitest"
import {
  ALL_EXTENSIONS,
  activeGroupsOf,
  breadcrumbOf,
  extensionOf,
  flattenDirectory,
  groupOf,
  isFiltering,
  listExtensions,
  matchRows,
  rowClassName,
  treeFromPaths,
  visibleRows,
  type DirectoryGroup,
  type DirectoryTreeNode,
} from "./directoryTree.ts"

const tree: DirectoryTreeNode = {
  name: "repo",
  children: [
    {
      name: "src",
      children: [
        { name: "app.py" },
        { name: "settings.JSON" },
        { name: "nested", children: [{ name: "helper.py" }] },
      ],
    },
    { name: "Makefile" },
  ],
}

const rows = flattenDirectory(tree)
const groups: DirectoryGroup[] = [
  { id: "money", label: "critical", tone: "danger", paths: ["repo/src/nested", "repo/src/app.py"] },
  { id: "docs", label: "docs", tone: "success", paths: ["repo/Makefile"] },
]

describe("extensionOf", () => {
  it("lowercases the extension and ignores dotfiles", () => {
    expect(extensionOf("app.py")).toBe(".py")
    expect(extensionOf("settings.JSON")).toBe(".json")
    expect(extensionOf("Makefile")).toBe("")
    expect(extensionOf(".gitignore")).toBe("")
  })
})

describe("flattenDirectory", () => {
  it("keeps the full path of every descendant", () => {
    expect(rows.map((row) => row.path)).toEqual([
      "repo",
      "repo/src",
      "repo/src/app.py",
      "repo/src/settings.JSON",
      "repo/src/nested",
      "repo/src/nested/helper.py",
      "repo/Makefile",
    ])
  })

  it("stores cumulative parent paths and depth", () => {
    const nested = rows.find((row) => row.path === "repo/src/nested")

    expect(nested?.parents).toEqual(["repo", "repo/src"])
    expect(nested?.depth).toBe(2)
    expect(nested?.isFolder).toBe(true)
    expect(rows.find((row) => row.path === "repo/Makefile")?.isFolder).toBe(false)
  })
})

describe("listExtensions", () => {
  it("lists unique lowercased extensions of files only, sorted", () => {
    expect(listExtensions(rows)).toEqual([".json", ".py"])
  })

  it("returns nothing for a tree without extensions", () => {
    expect(listExtensions(flattenDirectory({ name: "repo", children: [{ name: "Makefile" }] }))).toEqual([])
  })
})

describe("activeGroupsOf", () => {
  it("keeps only the groups touching a real path", () => {
    const withGhost: DirectoryGroup[] = [...groups, { id: "ghost", label: "ghost", tone: "info", paths: ["repo/nope.ts"] }]

    expect(activeGroupsOf(rows, withGhost).map((group) => group.id)).toEqual(["money", "docs"])
    expect(activeGroupsOf(rows, [])).toEqual([])
  })
})

describe("groupOf", () => {
  it("returns the first group holding the path", () => {
    const overlapping: DirectoryGroup[] = [
      { id: "first", label: "first", tone: "info", paths: ["repo/src"] },
      { id: "second", label: "second", tone: "danger", paths: ["repo/src"] },
    ]

    expect(groupOf(overlapping, "repo/src")?.id).toBe("first")
    expect(groupOf(groups, "repo/src")).toBeNull()
  })
})

describe("isFiltering", () => {
  it("is false only when nothing is set", () => {
    expect(isFiltering({ query: "", extension: ALL_EXTENSIONS })).toBe(false)
    expect(isFiltering({ query: "a", extension: ALL_EXTENSIONS })).toBe(true)
    expect(isFiltering({ query: "", extension: ".py" })).toBe(true)
  })
})

function sorted(values: Set<string>): string[] {
  return [...values].sort()
}

describe("matchRows", () => {
  it("keeps the matches and their ancestors, forcing them open", () => {
    const { shown, forced } = matchRows(rows, { query: "helper", extension: ALL_EXTENSIONS })

    expect(sorted(shown)).toEqual(["repo", "repo/src", "repo/src/nested", "repo/src/nested/helper.py"])
    expect(sorted(forced)).toEqual(["repo", "repo/src", "repo/src/nested"])
    expect(shown.has("repo/src/nested/helper.py")).toBe(true)
    expect(forced.has("repo/src/nested/helper.py")).toBe(false)
  })

  it("combines query and extension", () => {
    expect(sorted(matchRows(rows, { query: "settings", extension: ".json" }).shown))
      .toEqual(["repo", "repo/src", "repo/src/settings.JSON"])
    expect(sorted(matchRows(rows, { query: "app", extension: ".json" }).shown)).toEqual([])
  })

  it("never matches extensionless files or folders by extension", () => {
    expect(matchRows(rows, { query: "", extension: ALL_EXTENSIONS }).shown.size).toBe(rows.length)
    expect(sorted(matchRows(rows, { query: "", extension: ".md" }).shown)).toEqual([])
  })
})

describe("visibleRows", () => {
  const openAll = () => true

  it("returns everything without a match", () => {
    expect(visibleRows(rows, null, openAll)).toHaveLength(rows.length)
  })

  it("hides rows whose parents are closed", () => {
    expect(visibleRows(rows, null, (path) => path === "repo").map((row) => row.path))
      .toEqual(["repo", "repo/src", "repo/Makefile"])
    expect(visibleRows(rows, null, () => false).map((row) => row.path)).toEqual(["repo"])
  })
})

describe("rowClassName", () => {
  it("combines group, selection and flag independently", () => {
    expect(rowClassName(false, false, null)).toBe("directory-row")
    expect(rowClassName(true, false, null)).toBe("directory-row directory-row-active")
    expect(rowClassName(false, true, null)).toBe("directory-row directory-row-flagged")
    expect(rowClassName(true, true, groups[0] as DirectoryGroup))
      .toBe("directory-row directory-row-group-danger directory-row-active directory-row-flagged")
  })
})

describe("treeFromPaths", () => {
  it("nests the paths under the given root", () => {
    const tree = treeFromPaths("repo", ["src/app.py", "src/lib/util.ts", "README.md"])

    expect(tree.name).toBe("repo")
    expect(tree.children?.map((child) => child.name)).toEqual(["src", "README.md"])
    expect(tree.children?.[0]?.children?.map((child) => child.name)).toEqual(["lib", "app.py"])
    expect(tree.children?.[0]?.children?.[0]?.children?.map((child) => child.name)).toEqual(["util.ts"])
  })

  it("merges a folder that also appears as a file", () => {
    const tree = treeFromPaths("repo", ["src", "src/app.py"])

    expect(tree.children?.map((child) => child.name)).toEqual(["src"])
    expect(tree.children?.[0]?.children?.map((child) => child.name)).toEqual(["app.py"])
  })

  it("sorts folders before files, each alphabetically", () => {
    const tree = treeFromPaths("repo", ["z.ts", "src/b.ts", "src/a.ts", "a.ts", "Makefile"])

    expect(tree.children?.map((child) => child.name)).toEqual(["src", "Makefile", "a.ts", "z.ts"])
    expect(tree.children?.[0]?.children?.map((child) => child.name)).toEqual(["a.ts", "b.ts"])
  })

  it("ignores blank, dot and trailing slash segments", () => {
    const tree = treeFromPaths("repo", ["", "./src/app.py", "src/"])

    expect(tree.children?.map((child) => child.name)).toEqual(["src"])
    expect(flattenDirectory(tree).map((row) => row.path)).toEqual(["repo", "repo/src", "repo/src/app.py"])
  })

  it("returns a root with no children for an empty list", () => {
    expect(treeFromPaths("repo", [])).toEqual({ name: "repo", children: [] })
  })
})

describe("breadcrumbOf", () => {
  it("splits the path or returns nothing", () => {
    expect(breadcrumbOf("repo/src/app.py")).toEqual(["repo", "src", "app.py"])
    expect(breadcrumbOf(null)).toEqual([])
  })
})

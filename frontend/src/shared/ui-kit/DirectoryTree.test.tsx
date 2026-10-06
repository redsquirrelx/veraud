import { describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { DirectoryTree } from "./DirectoryTree.tsx"
import { flattenDirectory, type DirectoryGroup, type DirectoryTreeNode } from "./directoryTree.ts"

const tree: DirectoryTreeNode = {
  name: "repo",
  children: [
    { name: "src", children: [{ name: "a.ts" }, { name: "nested", children: [{ name: "b.ts" }] }] },
    { name: "README.md" },
  ],
}

const groups: DirectoryGroup[] = [
  { id: "money", label: "critical", tone: "danger", paths: ["repo/src/nested", "repo/src/a.ts"] },
  { id: "docs", label: "docs", tone: "success", paths: ["repo/README.md"] },
]

function row(name: string): HTMLElement {
  const list = screen.getByRole("tree")
  const button = within(list).getByText(name).closest("button")
  if (button === null || button === undefined) {
    throw new Error(`row ${name} not found`)
  }
  return button as HTMLElement
}

function selectedNames(): string[] {
  return screen
    .getAllByRole("treeitem")
    .filter((item) => item.getAttribute("aria-selected") === "true")
    .map((item) => within(item).getByText(/\S/).textContent ?? "")
}

function breadcrumb(): string[] {
  const nav = screen.getByRole("navigation", { name: "Breadcrumb" })
  return Array.from(nav.querySelectorAll(".directory-crumb")).map((crumb) => crumb.textContent ?? "")
}

describe("flattenDirectory", () => {
  it("keeps the full path of every descendant", () => {
    const rows = flattenDirectory(tree)

    expect(rows.map((entry) => entry.path)).toEqual([
      "repo",
      "repo/src",
      "repo/src/a.ts",
      "repo/src/nested",
      "repo/src/nested/b.ts",
      "repo/README.md",
    ])
  })

  it("stores cumulative parent paths and depth", () => {
    const rows = flattenDirectory(tree)
    const nested = rows.find((entry) => entry.path === "repo/src/nested")

    expect(nested?.parents).toEqual(["repo", "repo/src"])
    expect(nested?.depth).toBe(2)
    expect(nested?.isFolder).toBe(true)
    expect(rows.find((entry) => entry.path === "repo/README.md")?.isFolder).toBe(false)
  })
})
describe("DirectoryTree refresh", () => {
  it("hides the refresh control without a handler", () => {
    render(<DirectoryTree tree={tree} />)

    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull()
  })

  it("shows a spinner and blocks the filters while reloading", async () => {
    let release = () => {}
    const onRefresh = vi.fn(() => new Promise<void>((resolve) => {
      release = resolve
    }))
    const { container } = render(<DirectoryTree tree={tree} initialExpanded={["repo/src"]} onRefresh={onRefresh} />)

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))

    expect(screen.getByRole("status", { name: "Loading" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled()
    expect(screen.getByPlaceholderText("File or folder name")).toBeDisabled()
    expect(container.querySelector(".directory-tree-view")?.getAttribute("aria-busy")).toBe("true")

    release()
    await waitFor(() => expect(container.querySelector(".directory-tree-view")?.getAttribute("aria-busy")).toBe("false"))

    expect(onRefresh).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled()
  })

  it("ignores extra clicks while already reloading", async () => {
    let release = () => {}
    const onRefresh = vi.fn(() => new Promise<void>((resolve) => {
      release = resolve
    }))
    render(<DirectoryTree tree={tree} onRefresh={onRefresh} />)

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))

    expect(onRefresh).toHaveBeenCalledTimes(1)

    release()
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled())
  })

  it("re-enables the controls when the refresh fails", async () => {
    const onRefresh = vi.fn(async () => {
      throw new Error("boom")
    })
    render(<DirectoryTree tree={tree} onRefresh={onRefresh} />)

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))

    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled())
    expect(screen.getByPlaceholderText("File or folder name")).not.toBeDisabled()
  })
})

describe("DirectoryTree filters", () => {
  const deep: DirectoryTreeNode = {
    name: "repo",
    children: [
      {
        name: "src",
        children: [
          { name: "app.py" },
          { name: "settings.json" },
          { name: "nested", children: [{ name: "helper.py" }] },
        ],
      },
      { name: "Makefile" },
    ],
  }

  function names(): string[] {
    return screen.getAllByRole("treeitem").map((item) => item.textContent ?? "")
  }

  it("lists the extensions found in the tree", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByRole("button", { name: "All" }))

    expect(screen.getByRole("option", { name: ".json" })).toBeDefined()
    expect(screen.getByRole("option", { name: ".py" })).toBeDefined()
    expect(screen.queryByRole("option", { name: "" })).toBeNull()
  })

  it("filters by name and keeps the ancestors of the match", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.type(screen.getByPlaceholderText("File or folder name"), "helper")

    expect(names().some((text) => text.includes("helper.py"))).toBe(true)
    expect(names().some((text) => text.includes("settings.json"))).toBe(false)
    expect(names().some((text) => text.startsWith("src"))).toBe(true)
  })

  it("reveals matches hidden inside collapsed folders", async () => {
    render(<DirectoryTree tree={deep} />)

    await userEvent.type(screen.getByPlaceholderText("File or folder name"), "helper")

    expect(names().some((text) => text.includes("helper.py"))).toBe(true)
    expect(names().some((text) => text.includes("app.py"))).toBe(false)
  })

  it("filters by extension", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByRole("button", { name: "All" }))
    await userEvent.click(screen.getByRole("option", { name: ".py" }))

    const found = names().join("|")
    expect(found).toContain("app.py")
    expect(found).toContain("helper.py")
    expect(found).not.toContain("settings.json")
    expect(found).not.toContain("Makefile")
  })

  it("combines name and extension filters", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByRole("button", { name: "All" }))
    await userEvent.click(screen.getByRole("option", { name: ".py" }))
    await userEvent.type(screen.getByPlaceholderText("File or folder name"), "helper")

    const found = names().join("|")
    expect(found).toContain("helper.py")
    expect(found).not.toContain("app.py")
  })

  it("clears the filters when nothing matches", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.type(screen.getByPlaceholderText("File or folder name"), "zzz")

    expect(screen.getByText("No entries match the filter")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Clear" }))

    expect(screen.getByPlaceholderText("File or folder name")).toHaveValue("")
    expect(names().some((text) => text.includes("app.py"))).toBe(true)
  })
})

describe("DirectoryTree", () => {
  it("starts with only the root expanded", () => {
    render(<DirectoryTree tree={tree} />)

    expect(screen.getByText("repo")).toBeDefined()
    expect(screen.queryByText("a.ts")).toBeNull()
    expect(screen.getByText("No file selected")).toBeDefined()
  })

  it("expands folders and selects files", async () => {
    render(<DirectoryTree tree={tree} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByText("nested"))
    expect(screen.getByText("b.ts")).toBeDefined()

    await userEvent.click(screen.getByText("b.ts"))
    expect(selectedNames()).toEqual(["b.ts"])
    expect(breadcrumb()).toEqual(["repo", "src", "nested", "b.ts"])
  })

  it("starts with no selection reported in the breadcrumb", () => {
    render(<DirectoryTree tree={tree} />)

    expect(selectedNames()).toEqual([])
    expect(screen.getByText("No file selected")).toBeDefined()
  })

  it("shows the group legend at the bottom only when groups are provided", () => {
    const { container, rerender } = render(<DirectoryTree tree={tree} />)

    expect(screen.queryByText("critical")).toBeNull()
    expect(container.querySelector(".directory-legend")).toBeNull()

    rerender(<DirectoryTree tree={tree} groups={groups} initialExpanded={["repo/src"]} />)

    const legend = container.querySelector(".directory-legend")
    expect(legend).not.toBeNull()
    expect(within(legend as HTMLElement).getByText("critical")).toBeDefined()
    expect(within(legend as HTMLElement).getByText("docs")).toBeDefined()
    expect(within(legend as HTMLElement).queryByText("flagged")).toBeNull()

    const tree_ = container.querySelector(".directory-tree")
    expect(tree_?.compareDocumentPosition(legend as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it("colours every grouped path, folders included", () => {
    render(<DirectoryTree tree={tree} groups={groups} initialExpanded={["repo/src"]} />)

    expect(row("nested").className).toContain("directory-row-group-danger")
    expect(row("a.ts").className).toContain("directory-row-group-danger")
    expect(row("README.md").className).toContain("directory-row-group-success")
    expect(row("src").className).not.toContain("directory-row-group-")
    expect(within(row("nested")).getByText("critical")).toBeDefined()
  })

  it("shows flagged on top of the group colour", () => {
    render(<DirectoryTree tree={tree} groups={groups} flaggedPaths={["repo/src/nested"]} initialExpanded={["repo/src"]} />)

    expect(row("nested").className).toContain("directory-row-group-danger")
    expect(row("nested").className).toContain("directory-row-flagged")
    expect(within(row("nested")).getByText("critical")).toBeDefined()
    expect(within(row("nested")).getByText("flagged")).toBeDefined()
    expect(row("a.ts").className).not.toContain("directory-row-flagged")
  })

  it("keeps selection orthogonal to both axes", async () => {
    render(<DirectoryTree tree={tree} groups={groups} flaggedPaths={["repo/README.md"]} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByText("a.ts"))

    expect(row("a.ts").className).toContain("directory-row-active")
    expect(row("a.ts").className).toContain("directory-row-group-danger")
    expect(row("README.md").className).toContain("directory-row-flagged")
    expect(row("README.md").className).not.toContain("directory-row-active")
  })

  it("first group wins when a path belongs to two groups", () => {
    const overlapping: DirectoryGroup[] = [
      { id: "first", label: "first", tone: "info", paths: ["repo/src"] },
      { id: "second", label: "second", tone: "danger", paths: ["repo/src"] },
    ]
    render(<DirectoryTree tree={tree} groups={overlapping} initialExpanded={["repo/src"]} />)

    expect(within(row("src")).getByText("first")).toBeDefined()
    expect(within(row("src")).queryByText("second")).toBeNull()
  })

  it("ignores groups and flags that do not exist", () => {
    render(<DirectoryTree tree={tree} groups={[{ id: "ghost", label: "ghost", tone: "info", paths: ["repo/ghost.ts"] }]} flaggedPaths={["repo/nope.ts"]} />)

    expect(screen.queryByText("flagged")).toBeNull()
    expect(screen.queryByText("ghost")).toBeNull()
  })

  it("keeps collapsing folders when no filter is active", async () => {
    render(<DirectoryTree tree={tree} initialExpanded={["repo/src"]} />)

    await userEvent.click(within(screen.getByRole("tree")).getByText("src"))

    expect(screen.queryByText("a.ts")).toBeNull()

    await userEvent.click(within(screen.getByRole("tree")).getByText("src"))

    expect(screen.getByText("a.ts")).toBeDefined()
  })
})

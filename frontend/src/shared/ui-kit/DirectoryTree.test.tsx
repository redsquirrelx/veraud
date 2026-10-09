import { describe, expect, it, vi } from "vitest"
import { useState } from "react"
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
    .map((item) => item.querySelector(".mono")?.textContent ?? "")
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

  it("opens an overflow menu with working filter controls", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByRole("button", { name: "More filters" }))

    const panel = screen.getByRole("menu", { name: "More filters" })
    expect(panel).toBeDefined()

    await userEvent.type(within(panel).getByPlaceholderText("File or folder name"), "helper")

    expect(names().some((text) => text.includes("helper.py"))).toBe(true)
    expect(names().some((text) => text.includes("app.py"))).toBe(false)
  })

  it("closes the overflow menu with escape", async () => {
    render(<DirectoryTree tree={deep} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByRole("button", { name: "More filters" }))
    expect(screen.getByRole("menu", { name: "More filters" })).toBeDefined()

    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("menu", { name: "More filters" })).toBeNull()
  })
})

describe("DirectoryTree", () => {
  it("starts with only the root expanded and nothing selected", () => {
    render(<DirectoryTree tree={tree} />)

    expect(screen.getByText("repo")).toBeDefined()
    expect(screen.queryByText("a.ts")).toBeNull()
    expect(screen.getByText("No file selected")).toBeDefined()
    expect(selectedNames()).toEqual([])
  })

  it("expands folders and selects files", async () => {
    render(<DirectoryTree tree={tree} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByText("nested"))
    expect(screen.getByText("b.ts")).toBeDefined()

    await userEvent.click(screen.getByText("b.ts"))
    expect(selectedNames()).toEqual(["b.ts"])
    expect(breadcrumb()).toEqual(["repo", "src", "nested", "b.ts"])
  })

  it("shows the group legend at the bottom only when groups are provided", () => {
    const { unmount } = render(<DirectoryTree tree={tree} />)

    expect(screen.queryByText("critical")).toBeNull()
    unmount()

    render(<DirectoryTree tree={tree} groups={groups} initialExpanded={["repo/src", "repo/src/nested"]} />)

    // Row tags plus exactly one legend entry per group.
    expect(screen.getAllByText("critical").length).toBe(3)
    expect(screen.getAllByText("docs").length).toBe(2)
    expect(screen.queryByText("flagged")).toBeNull()
  })

  it("colours every grouped path, folders included", () => {
    render(<DirectoryTree tree={tree} groups={groups} initialExpanded={["repo/src"]} />)

    expect(row("nested").textContent).toContain("critical")
    expect(row("a.ts").textContent).toContain("critical")
    expect(row("README.md").textContent).toContain("docs")
    expect(row("src").textContent).not.toContain("critical")
  })

  it("shows flagged on top of the group colour", () => {
    render(<DirectoryTree tree={tree} groups={groups} flaggedPaths={["repo/src/nested"]} initialExpanded={["repo/src"]} />)

    expect(row("nested").textContent).toContain("critical")
    expect(row("nested").textContent).toContain("flagged")
    expect(row("a.ts").textContent).not.toContain("flagged")
  })

  it("keeps selection orthogonal to both axes", async () => {
    render(<DirectoryTree tree={tree} groups={groups} flaggedPaths={["repo/README.md"]} initialExpanded={["repo/src"]} />)

    await userEvent.click(screen.getByText("a.ts"))

    expect(selectedNames()).toEqual(["a.ts"])
    expect(row("a.ts").textContent).toContain("critical")
    expect(row("README.md").textContent).toContain("flagged")
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

  it("notifies the selected file without notifying folders", async () => {
    const selected: string[] = []
    render(<DirectoryTree tree={tree} initialExpanded={["repo/src"]} onSelectFile={(path) => { selected.push(path) }} />)

    await userEvent.click(screen.getByText("nested"))
    expect(selected).toEqual([])

    await userEvent.click(screen.getByText("a.ts"))
    expect(selected).toEqual(["repo/src/a.ts"])
  })

  it("keeps collapsing folders when no filter is active", async () => {
    render(<DirectoryTree tree={tree} initialExpanded={["repo/src"]} />)

    await userEvent.click(within(screen.getByRole("tree")).getByText("src"))

    expect(screen.queryByText("a.ts")).toBeNull()

    await userEvent.click(within(screen.getByRole("tree")).getByText("src"))

    expect(screen.getByText("a.ts")).toBeDefined()
  })
})

const gatewayTree: DirectoryTreeNode = {
  name: "payment-gateway-v2",
  children: [
    {
      name: "src",
      children: [
        {
          name: "modules",
          children: [
            { name: "settlement.ts" },
            { name: "ledger.repository.ts" },
            {
              name: "reconciliation",
              children: [{ name: "engine.ts" }, { name: "engine.test.ts" }],
            },
          ],
        },
        { name: "index.ts" },
        { name: "server.ts" },
      ],
    },
    { name: "package.json" },
    { name: "README.md" },
    { name: "tsconfig.json" },
  ],
}

const gatewayGroups: DirectoryGroup[] = [
  {
    id: "money",
    label: "critical",
    tone: "danger",
    paths: [
      "payment-gateway-v2/src/modules/reconciliation",
      "payment-gateway-v2/src/modules/reconciliation/engine.ts",
      "payment-gateway-v2/src/modules/settlement.ts",
    ],
  },
  {
    id: "infra",
    label: "infrastructure",
    tone: "info",
    paths: ["payment-gateway-v2/src/server.ts", "payment-gateway-v2/tsconfig.json"],
  },
  {
    id: "docs",
    label: "docs",
    tone: "success",
    paths: ["payment-gateway-v2/README.md"],
  },
]

const gatewayFlagged = [
  "payment-gateway-v2/src/modules/reconciliation/engine.ts",
  "payment-gateway-v2/src/server.ts",
]

const gatewayOpen = [
  "payment-gateway-v2/src",
  "payment-gateway-v2/src/modules",
  "payment-gateway-v2/src/modules/reconciliation",
]

function gatewaySelected(): string[] {
  return screen
    .getAllByRole("treeitem")
    .filter((item) => item.getAttribute("aria-selected") === "true")
    .map((item) => within(item).getByText(/\S/).textContent ?? "")
}

describe("grouped and flagged trees", () => {
  it("shows a plain tree without any tag", () => {
    render(
      <DirectoryTree
        tree={gatewayTree}
        initialExpanded={["payment-gateway-v2/src", "payment-gateway-v2/src/modules"]}
        initialSelected="payment-gateway-v2/src/modules/ledger.repository.ts"
      />
    )

    const list = screen.getByRole("tree")
    expect(within(list).getByText("modules")).toBeDefined()
    expect(within(list).queryByText("flagged")).toBeNull()
    expect(list.querySelectorAll(".directory-tag").length).toBe(0)
  })

  it("collapses and expands a folder", async () => {
    render(
      <DirectoryTree
        tree={gatewayTree}
        initialExpanded={["payment-gateway-v2/src", "payment-gateway-v2/src/modules"]}
      />
    )

    const list = screen.getByRole("tree")
    await userEvent.click(within(list).getByText("modules"))

    expect(within(list).queryByText("settlement.ts")).toBeNull()

    await userEvent.click(within(list).getByText("modules"))

    expect(within(list).getByText("settlement.ts")).toBeDefined()
  })

  it("selects a file and reflects it in the breadcrumb", async () => {
    render(
      <DirectoryTree
        tree={gatewayTree}
        initialExpanded={["payment-gateway-v2/src", "payment-gateway-v2/src/modules"]}
      />
    )

    await userEvent.click(within(screen.getByRole("tree")).getByText("ledger.repository.ts"))

    expect(breadcrumb()).toEqual(["payment-gateway-v2", "src", "modules", "ledger.repository.ts"])
    expect(gatewaySelected().join()).toContain("ledger.repository.ts")
  })

  it("reveals nested folders on demand", async () => {
    render(
      <DirectoryTree
        tree={gatewayTree}
        initialExpanded={["payment-gateway-v2/src", "payment-gateway-v2/src/modules"]}
      />
    )

    const list = screen.getByRole("tree")
    expect(within(list).getByText("reconciliation")).toBeDefined()

    await userEvent.click(within(list).getByText("reconciliation"))

    expect(within(list).getByText("engine.test.ts")).toBeDefined()
  })

  it("shows group tags next to grouped paths", () => {
    render(<DirectoryTree tree={gatewayTree} groups={gatewayGroups} initialExpanded={gatewayOpen} />)

    const list = screen.getByRole("tree")
    expect(within(list).getAllByText("critical").length).toBe(3)
    expect(within(list).getAllByText("infrastructure").length).toBe(2)
    expect(within(list).getAllByText("docs").length).toBe(1)
    expect(within(list).queryByText("flagged")).toBeNull()
  })

  it("combines group tags with flagged markers", () => {
    render(
      <DirectoryTree
        tree={gatewayTree}
        groups={gatewayGroups}
        flaggedPaths={gatewayFlagged}
        initialExpanded={gatewayOpen}
      />
    )

    const list = screen.getByRole("tree")
    expect(within(list).getAllByText("flagged").length).toBe(2)
    expect(within(list).getByText("engine.ts").closest("button")?.textContent).toContain("flagged")
    expect(within(list).getByText("settlement.ts").closest("button")?.textContent).not.toContain("flagged")
  })

  it("shows flagged markers without any group", () => {
    render(
      <DirectoryTree
        tree={gatewayTree}
        flaggedPaths={gatewayFlagged}
        initialExpanded={gatewayOpen}
        initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
      />
    )

    const list = screen.getByRole("tree")
    expect(within(list).getAllByText("flagged").length).toBe(2)
    expect(within(list).getByText("engine.ts").closest("button")?.textContent).toContain("flagged")
    expect(within(list).getByText("settlement.ts").closest("button")?.textContent).not.toContain("flagged")
  })

  it("reloads the directory and shows the new entry", async () => {
    function Harness() {
      const [revision, setRevision] = useState(0)
      const current: DirectoryTreeNode = {
        ...gatewayTree,
        children: [
          ...(gatewayTree.children ?? []),
          ...(revision > 0 ? [{ name: `generated-${revision}.ts` }] : []),
        ],
      }
      async function reload() {
        await new Promise<void>((resolve) => setTimeout(resolve, 20))
        setRevision((value) => value + 1)
      }
      return (
        <div>
          <span className="label">Reloading the directory (revision {revision})</span>
          <DirectoryTree tree={current} groups={gatewayGroups} flaggedPaths={gatewayFlagged} initialExpanded={gatewayOpen} onRefresh={reload} />
        </div>
      )
    }
    render(<Harness />)

    expect(screen.getByText("Reloading the directory (revision 0)")).toBeDefined()
    expect(screen.queryByText("generated-1.ts")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }))

    expect(await screen.findByText("Reloading the directory (revision 1)")).toBeDefined()
    expect(screen.getByText("generated-1.ts")).toBeDefined()
    expect(within(screen.getByRole("tree")).getAllByText("flagged").length).toBe(2)
  })

  it("keeps selection independent per instance", async () => {
    render(
      <>
        <DirectoryTree tree={gatewayTree} initialExpanded={gatewayOpen} />
        <DirectoryTree
          tree={gatewayTree}
          initialExpanded={gatewayOpen}
          initialSelected="payment-gateway-v2/src/modules/reconciliation/engine.ts"
        />
      </>
    )

    const lists = screen.getAllByRole("tree")
    await userEvent.click(within(lists[0] as HTMLElement).getByText("README.md"))

    const first = Array.from((lists[0] as HTMLElement).querySelectorAll('[role="treeitem"][aria-selected="true"]'))
      .map((item) => item.textContent ?? "").join()
    const second = Array.from((lists[1] as HTMLElement).querySelectorAll('[role="treeitem"][aria-selected="true"]'))
      .map((item) => item.textContent ?? "").join()
    expect(first).toContain("README.md")
    expect(second).toContain("engine.ts")
  })
})

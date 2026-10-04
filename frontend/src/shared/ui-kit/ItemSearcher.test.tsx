import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ItemSearcher } from "./ItemSearcher.tsx"

const items = [
  { id: "main", label: "main" },
  { id: "feature-a", label: "feature-a", detail: "3 commits ahead" },
]

describe("ItemSearcher", () => {
  it("filters the list while typing", async () => {
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} />
    )

    await userEvent.click(screen.getByLabelText("Search items"))
    expect(screen.getByRole("option", { name: /main/ })).toBeDefined()

    await userEvent.type(screen.getByLabelText("Search items"), "feature")

    expect(screen.queryByRole("option", { name: /^main/ })).toBeNull()
    expect(screen.getByRole("option", { name: /feature-a/ })).toBeDefined()
  })

  it("shows every item when opening with staged text", async () => {
    render(
      <ItemSearcher items={items} selectedId="main" onSelect={() => {}} hasMore={false} onLoadMore={() => {}} />
    )

    expect(screen.getByLabelText("Search items")).toHaveValue("main")

    await userEvent.click(screen.getByLabelText("Search items"))

    expect(screen.getByRole("option", { name: /^main/ })).toBeDefined()
    expect(screen.getByRole("option", { name: /feature-a/ })).toBeDefined()
  })

  it("selects an item from the filtered list", async () => {
    const onSelect = vi.fn()
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={onSelect} hasMore={false} onLoadMore={() => {}} />
    )

    await userEvent.type(screen.getByLabelText("Search items"), "feature")
    await userEvent.click(screen.getByRole("option", { name: /feature-a/ }))

    expect(onSelect).toHaveBeenCalledWith("feature-a")
    expect(screen.queryByRole("option")).toBeNull()
    expect(screen.getByLabelText("Search items")).toHaveValue("feature-a")
  })

  it("selects a typed id directly with Enter", async () => {
    const onSelect = vi.fn()
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={onSelect} hasMore={false} onLoadMore={() => {}} />
    )

    await userEvent.type(screen.getByLabelText("Search items"), "hotfix-9{enter}")

    expect(onSelect).toHaveBeenCalledWith("hotfix-9")
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("stages a typed id on blur without Enter", async () => {
    const onSelect = vi.fn()
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={onSelect} hasMore={false} onLoadMore={() => {}} />
    )

    await userEvent.type(screen.getByLabelText("Search items"), "hotfix-9")
    await userEvent.click(document.body)

    expect(onSelect).toHaveBeenCalledWith("hotfix-9")
    expect(screen.getByLabelText("Search items")).toHaveValue("hotfix-9")
  })

  it("clears the input restoring every item", async () => {
    const onSelect = vi.fn()
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={onSelect} hasMore={false} onLoadMore={() => {}} />
    )

    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull()

    await userEvent.type(screen.getByLabelText("Search items"), "feature")

    expect(screen.queryByRole("option", { name: /^main/ })).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Clear search" }))

    expect(screen.getByLabelText("Search items")).toHaveValue("")
    expect(screen.getByRole("option", { name: /^main/ })).toBeDefined()
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull()
  })

  it("keeps loading more while searching", async () => {
    const onLoadMore = vi.fn()
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={() => {}} hasMore onLoadMore={onLoadMore} />
    )

    await userEvent.click(screen.getByLabelText("Open items"))
    await userEvent.click(screen.getByText("Load more..."))

    expect(onLoadMore).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("option", { name: /main/ })).toBeDefined()
  })

  it("disables the input and toggle when disabled", async () => {
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} disabled />
    )

    expect(screen.getByLabelText("Search items")).toBeDisabled()
    expect(screen.getByLabelText("Open items")).toBeDisabled()
  })

  it("renders the floating label and loading state", () => {
    render(
      <ItemSearcher items={[]} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} label="Commit" loading />
    )

    expect(screen.getByText("Commit")).toBeDefined()
    expect(screen.getByText("Loading")).toBeDefined()
    expect(screen.getByRole("button")).toBeDisabled()
    expect(screen.queryByLabelText("Search items")).toBeNull()
  })

  it("shows loading instead of empty text while loading", () => {
    render(
      <ItemSearcher items={[]} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} loading />
    )

    expect(screen.getByText("Loading")).toBeDefined()
    expect(screen.getByRole("button")).toBeDisabled()
    expect(screen.queryByLabelText("Search items")).toBeNull()
    expect(screen.queryByText("No matches")).toBeNull()
  })

  it("shows the empty text without matches", async () => {
    render(
      <ItemSearcher items={items} selectedId={null} onSelect={() => {}} hasMore={false} onLoadMore={() => {}} />
    )

    await userEvent.type(screen.getByLabelText("Search items"), "zzz")

    expect(screen.getByText("No matches")).toBeDefined()
  })
})

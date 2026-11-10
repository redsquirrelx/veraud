import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { VersionSelector } from "./VersionSelector.tsx"
import { useVersionSelector } from "./useVersionSelector.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

const first = "a".repeat(40)
const second = "b".repeat(40)
const featureHash = "c".repeat(40)

interface Seen {
  url: string
  method: string
  body: Record<string, unknown>
}

function stubGit(options?: { branches?: string[], failCheckout?: boolean, detached?: string }) {
  const seen: Seen[] = []
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const body = init?.body === undefined ? {} : (JSON.parse(String(init.body)) as Record<string, unknown>)
    seen.push({ url, method: init?.method ?? "GET", body })
    if (url.includes("/git/branches")) {
      const names = options?.branches ?? ["feature", "main"]
      return new Response(JSON.stringify({
        branches: names,
        currentBranch: options?.detached === undefined ? "main" : null,
        detachedHash: options?.detached ?? null,
        taskId: 1,
      }), { status: 200 })
    }
    if (url.includes("/git/log")) {
      const commits = body["branch"] === "feature"
        ? [{ commitHash: featureHash, subject: "feature work" }]
        : [{ commitHash: first, subject: "second commit" }, { commitHash: second, subject: "first commit" }]
      return new Response(JSON.stringify({ branch: body["branch"], commits, limit: 30, offset: 0, taskId: 2 }), { status: 200 })
    }
    if (url.includes("/git/checkout-branch")) {
      return new Response(JSON.stringify({ branch: body["branch"], taskId: 5 }), { status: 200 })
    }
    if (url.includes("/git/checkout")) {
      if (options?.failCheckout === true) {
        return new Response(JSON.stringify({ message: "Could not check out" }), { status: 422 })
      }
      return new Response(JSON.stringify({ commitHash: body["commitHash"], taskId: 3 }), { status: 200 })
    }
    return new Response(JSON.stringify([]), { status: 200 })
  }) as typeof fetch
  return seen
}

function renderSelector(onApplied?: (version: { branch: string, commitHash: string }) => void) {
  function Harness() {
    const selection = useVersionSelector(2, onApplied === undefined ? undefined : { onApplied })
    return <VersionSelector selection={selection} />
  }
  render(<Harness />)
}

function branchDropdown(): HTMLElement {
  const label = screen.getByText("Branch")
  const row = label.closest(".version-row")
  if (row === null) {
    throw new Error("Branch row not found")
  }
  return row as HTMLElement
}

describe("VersionSelector", () => {
  it("shows a spinner and message while the version is loading", async () => {
    globalThis.fetch = (async (input: unknown) => {
      const url = String(input)
      if (url.includes("/git/branches")) return new Promise<Response>(() => {})
      if (url.includes("/git/log")) {
        return new Response(JSON.stringify({ branch: "main", commits: [{ commitHash: first, subject: "second commit" }], limit: 30, offset: 0, taskId: 2 }), { status: 200 })
      }
      return new Response(JSON.stringify([]), { status: 200 })
    }) as typeof fetch
    renderSelector()

    expect(await screen.findByText("Loading version (branch and commit)…")).toBeDefined()
    expect(document.querySelector(".version-loading .ui-spinner")).not.toBeNull()
  })
  it.each(["git", "analyzed"] as const)("locks %s version selection through the disabled prop", async (mode) => {
    stubGit()
    function Harness({ disabled }: { disabled: boolean }) {
      const selection = useVersionSelector(2)
      return <VersionSelector selection={selection} disabled={disabled} mode={mode} onModeChange={() => {}}
        analyzed={{ versions: [], loading: false, error: "", selectedId: null, onSelect: () => {}, onRefresh: () => {} }} />
    }
    const { rerender } = render(<Harness disabled={false} />)
    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    rerender(<Harness disabled />)
    expect(screen.getByRole("tab", { name: "Git" })).toBeDisabled()
    expect(screen.getByRole("tab", { name: /Analyzed/ })).toBeDisabled()
    if (mode === "git") {
      expect(screen.getByRole("button", { name: "main" })).toBeDisabled()
      expect(screen.getByRole("textbox", { name: "Search items" })).toBeDisabled()
    } else expect(screen.getByRole("button", { name: "Select an analyzed version" })).toBeDisabled()
  })
  it("defaults to the main branch and its latest commit", async () => {
    stubGit()
    renderSelector()

    expect(await screen.findByText(`On main at ${first.slice(0, 7)}`)).toBeDefined()
    expect(within(branchDropdown()).getByRole("button", { name: "main" })).toBeDefined()
    expect(screen.getByLabelText("Search items")).toHaveValue(first.slice(0, 7))
    expect(screen.queryByRole("button", { name: "Apply version" })).toBeNull()

    await userEvent.click(screen.getByLabelText("Search items"))

    expect(screen.getByText("(HEAD) second commit")).toBeDefined()
    expect(screen.getByText("first commit")).toBeDefined()
  })

  it("selects the latest commit when the branch changes", async () => {
    const seen = stubGit()
    renderSelector()

    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    await userEvent.click(within(branchDropdown()).getByRole("button", { name: "main" }))
    await userEvent.click(screen.getByRole("option", { name: "feature" }))

    await waitFor(() => expect(screen.getByLabelText("Search items")).toHaveValue(featureHash.slice(0, 7)))
    expect(await screen.findByText(`On feature at ${featureHash.slice(0, 7)}`)).toBeDefined()
    const switched = seen.find((call) => call.url.includes("/git/checkout-branch"))
    expect(switched?.body["branch"]).toEqual("feature")
  })

  it("does not check out when selecting the applied commit again", async () => {
    const seen = stubGit()
    renderSelector()

    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.click(screen.getByRole("option", { name: new RegExp(first.slice(0, 7)) }))

    await waitFor(() => expect(screen.getByLabelText("Search items")).toHaveValue(first.slice(0, 7)))
    expect(seen.some((call) => call.url.includes("/git/checkout"))).toBe(false)
    expect(screen.queryByText(/HEAD detached/)).toBeNull()
  })

  it("checks out a non-tip commit on select and shows detached", async () => {
    const seen = stubGit()
    const applied = vi.fn()
    renderSelector(applied)

    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.click(screen.getByRole("option", { name: new RegExp(second.slice(0, 7)) }))

    await waitFor(() => expect(applied).toHaveBeenCalledWith({ branch: "main", commitHash: second }))
    expect(await screen.findByText(`(HEAD detached at ${second}) - select a branch to re-attach`)).toBeDefined()
    expect(screen.getByLabelText("Search items")).toBeDisabled()
    const checkout = seen.find((call) => call.url.includes("/git/checkout") && !call.url.includes("checkout-branch"))
    expect(checkout?.body["commitHash"]).toEqual(second)
  })

  it("checks out a typed hash directly", async () => {
    const seen = stubGit()
    renderSelector()

    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.type(screen.getByLabelText("Search items"), `${featureHash}{enter}`)

    expect(await screen.findByText(`(HEAD detached at ${featureHash}) - select a branch to re-attach`)).toBeDefined()
    const checkout = seen.find((call) => call.url.includes("/git/checkout") && !call.url.includes("checkout-branch"))
    expect(checkout?.body["commitHash"]).toEqual(featureHash)
  })

  it("rejects invalid hashes without calling checkout", async () => {
    const seen = stubGit()
    renderSelector()

    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.type(screen.getByLabelText("Search items"), "xyz{enter}")

    expect(await screen.findByText("Commit hash must be 7 to 40 hex characters")).toBeDefined()
    expect(seen.some((call) => call.url.includes("/git/checkout"))).toBe(false)
  })

  it("shows checkout errors", async () => {
    stubGit({ failCheckout: true })
    renderSelector()

    await screen.findByText(`On main at ${first.slice(0, 7)}`)
    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.click(screen.getByRole("option", { name: new RegExp(second.slice(0, 7)) }))

    expect(await screen.findByText("Could not check out")).toBeDefined()
  })

  it("restores a detached HEAD on load and blocks commits", async () => {
    stubGit({ detached: featureHash })
    renderSelector()

    expect(await screen.findByText(`(HEAD detached at ${featureHash}) - select a branch to re-attach`)).toBeDefined()
    expect(screen.getByLabelText("Search items")).toBeDisabled()
    expect(screen.getByLabelText("Search items")).toHaveValue(featureHash)
  })

  it("clears detached by selecting another branch", async () => {
    const seen = stubGit({ detached: featureHash })
    renderSelector()

    await screen.findByText(`(HEAD detached at ${featureHash}) - select a branch to re-attach`)

    await userEvent.click(screen.getByRole("button", { name: `(HEAD detached at ${featureHash})` }))
    await userEvent.click(screen.getByRole("option", { name: "main" }))

    await waitFor(() => expect(screen.getByLabelText("Search items")).toHaveValue(first.slice(0, 7)))
    expect(screen.queryByText(/HEAD detached/)).toBeNull()
    expect(screen.getByLabelText("Search items")).not.toBeDisabled()
    const switched = seen.find((call) => call.url.includes("/git/checkout-branch"))
    expect(switched?.body["branch"]).toEqual("main")
  })
})

import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Sidebar } from "./Sidebar.tsx"
import { FolderIcon } from "./icons.tsx"
import { changeLanguage } from "../i18n/index.ts"

afterEach(async () => { await changeLanguage("en") })

const items = [
  { id: "home", label: "Home", icon: <FolderIcon /> },
  { id: "settings", label: "Settings", icon: <FolderIcon /> },
]

describe("Sidebar", () => {
  it("animates resizing and reverses from the visible width on a rapid toggle", async () => {
    const user = userEvent.setup()
    const { container } = render(<Sidebar title="Menu" items={items} />)
    const sidebar = screen.getByRole("complementary", { name: "Menu" })
    const cancel = vi.fn()
    const animate = vi.fn<HTMLElement["animate"]>(() => ({ cancel }) as unknown as Animation)
    sidebar.animate = animate
    const rectangle = (width: number) => ({ width, height: 600 }) as DOMRect
    vi.spyOn(sidebar, "getBoundingClientRect")
      .mockReturnValueOnce(rectangle(220))
      .mockReturnValueOnce(rectangle(48))
      .mockReturnValueOnce(rectangle(140))
      .mockReturnValueOnce(rectangle(220))
    const contentAnimate = vi.fn(() => ({ cancel: vi.fn() }) as unknown as Animation)
    container.querySelectorAll<HTMLElement>(".ui-sidebar-top, .ui-sidebar-nav").forEach((element) => { element.animate = contentAnimate })
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }))
    expect(animate.mock.calls[0][0]).toEqual([
      expect.objectContaining({ width: "220px" }),
      expect.objectContaining({ width: "48px" }),
    ])
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }))
    expect(cancel).toHaveBeenCalled()
    expect(animate.mock.calls[1][0]).toEqual([
      expect.objectContaining({ width: "140px" }),
      expect.objectContaining({ width: "220px" }),
    ])
    expect(contentAnimate).toHaveBeenCalledTimes(2)
  })

  it("shows details while expanded", () => {
    render(<Sidebar title="Menu" items={items} activeId="home" />)

    expect(screen.getByText("Menu")).toBeDefined()
    expect(screen.getByText("Home")).toBeDefined()
    expect(screen.getByText("Settings")).toBeDefined()
  })

  it("hides details when collapsed", async () => {
    render(<Sidebar title="Menu" items={items} />)

    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }))

    expect(screen.queryByText("Menu")).toBeNull()
    expect(screen.queryByText("Home")).toBeNull()
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
  })

  it("notifies the selected item", async () => {
    const onSelect = vi.fn()
    render(<Sidebar title="Menu" items={items} onSelect={onSelect} />)

    await userEvent.click(screen.getByRole("button", { name: "Settings" }))

    expect(onSelect).toHaveBeenCalledWith("settings")
  })

  it("persists the collapsed state through storage", async () => {
    window.localStorage.clear()
    const { unmount } = render(<Sidebar title="Menu" items={items} storageKey="sidebar.test" />)

    await userEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }))
    unmount()

    render(<Sidebar title="Menu" items={items} storageKey="sidebar.test" />)

    expect(screen.queryByText("Home")).toBeNull()
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
    window.localStorage.clear()
  })

  it("translates the accessible toggle names and section label", async () => {
    await changeLanguage("es")
    render(<Sidebar title="Menu" items={items} />)

    expect(screen.getByRole("navigation", { name: "Secciones de Menu" })).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Contraer barra lateral" }))
    expect(screen.getByRole("button", { name: "Expandir barra lateral" })).toBeInTheDocument()
  })
})

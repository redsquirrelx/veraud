import { describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Pagination } from "./Pagination.tsx"

describe("Pagination", () => {
  it("renders nothing on a single page", () => {
    const { container } = render(<Pagination page={1} pageCount={1} onChange={() => {}} />)

    expect(container).toBeEmptyDOMElement()
  })

  it("shows the current page and navigates", async () => {
    const onChange = vi.fn()
    render(<Pagination page={2} pageCount={3} onChange={onChange} />)

    expect(screen.getByText("Page 2 of 3")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Next page" }))
    expect(onChange).toHaveBeenCalledWith(3)

    await userEvent.click(screen.getByRole("button", { name: "Previous page" }))
    expect(onChange).toHaveBeenCalledWith(1)
  })

  it("disables the edges", () => {
    const { unmount } = render(<Pagination page={1} pageCount={3} onChange={() => {}} />)

    expect(screen.getByRole("button", { name: "Previous page" }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(false)
    unmount()

    render(<Pagination page={3} pageCount={3} onChange={() => {}} />)

    expect(screen.getByRole("button", { name: "Previous page" }).hasAttribute("disabled")).toBe(false)
    expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(true)
  })
})

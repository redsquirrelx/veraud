import { afterEach, expect, it, vi } from "vitest"
import { render, waitFor } from "@testing-library/react"
import { CodeViewer } from "./CodeViewer.tsx"

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
const code = Array.from({ length: 100 }, (_, index) => `const value${index} = ${index}`).join("\n")

it("smoothly scrolls the viewer to the highlighted source line without moving the page", async () => {
  const pageScroll = vi.spyOn(window, "scrollTo")
  const { container, rerender } = render(<CodeViewer code={code} scrollToLine={70} />)
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  const scroll = vi.fn()
  viewport.scrollTo = scroll
  viewport.getBoundingClientRect = () => ({ top: 100 }) as DOMRect
  container.querySelector<HTMLElement>('[data-line="70"]')!.getBoundingClientRect = () => ({ top: 1480 }) as DOMRect
  await waitFor(() => expect(scroll).toHaveBeenCalledWith({ top: 1380, behavior: "smooth" }))
  expect(pageScroll).not.toHaveBeenCalled()
  rerender(<CodeViewer code={code} scrollToLine={70} />)
  expect(scroll).toHaveBeenCalledTimes(1)
  container.querySelector<HTMLElement>('[data-line="30"]')!.getBoundingClientRect = () => ({ top: 680 }) as DOMRect
  rerender(<CodeViewer code={code} scrollToLine={30} />)
  await waitFor(() => expect(scroll).toHaveBeenLastCalledWith({ top: 580, behavior: "smooth" }))
})

it("uses instant internal scrolling when reduced motion is requested", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }))
  const { container } = render(<CodeViewer code={code} scrollToLine={4} />)
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  viewport.scrollTo = vi.fn()
  await waitFor(() => expect(viewport.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: "auto" }))
})

it("waits for the requested line in a progressively rendered large file", async () => {
  const large = Array.from({ length: 1200 }, (_, index) => `line ${index + 1}`).join("\n")
  const { container } = render(<CodeViewer code={large} scrollToLine={1100} />)
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  viewport.scrollTo = vi.fn()
  await waitFor(() => expect(viewport.scrollTo).toHaveBeenCalledTimes(1))
  expect(container.querySelector('[data-line="1100"]')).not.toBeNull()
})

it("does not scroll when no source target is available", async () => {
  const { container, rerender } = render(<CodeViewer code={code} />)
  const viewport = container.querySelector<HTMLPreElement>(".ui-code-body")!
  viewport.scrollTo = vi.fn()
  rerender(<CodeViewer code={code} scrollToLine={999} />)
  await new Promise((resolve) => setTimeout(resolve, 10))
  expect(viewport.scrollTo).not.toHaveBeenCalled()
})

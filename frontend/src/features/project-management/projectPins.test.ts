import { afterEach, describe, expect, it } from "vitest"
import { loadPinnedProjects, savePinnedProjects } from "./projectPins.ts"

afterEach(() => {
  window.localStorage.removeItem("projects.pinned")
})

describe("projectPins", () => {
  it("starts empty without stored pins", () => {
    expect(loadPinnedProjects()).toEqual([])
  })

  it("roundtrips pinned ids", () => {
    savePinnedProjects([3, 1])

    expect(loadPinnedProjects()).toEqual([3, 1])
  })

  it("ignores non-array payloads", () => {
    window.localStorage.setItem("projects.pinned", JSON.stringify({ id: 1 }))

    expect(loadPinnedProjects()).toEqual([])
  })

  it("keeps only integer ids", () => {
    window.localStorage.setItem("projects.pinned", JSON.stringify([2, "x", 1.5, null, 7]))

    expect(loadPinnedProjects()).toEqual([2, 7])
  })

  it("falls back on corrupt json", () => {
    window.localStorage.setItem("projects.pinned", "{broken")

    expect(loadPinnedProjects()).toEqual([])
  })
})

import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook } from "@testing-library/react"
import {
  defaultTaskVisibility,
  isTaskVisible,
  loadTaskVisibility,
  saveTaskVisibility,
  useTaskVisibility,
} from "./taskVisibility.ts"

afterEach(() => {
  window.localStorage.removeItem("tasks.visibility")
})

describe("taskVisibility", () => {
  it("hides read tasks but shows mutating ones by default", () => {
    const defaults = defaultTaskVisibility()

    expect(defaults["clone"]).toBe(true)
    expect(defaults["pull"]).toBe(true)
    expect(defaults["fetch"]).toBe(true)
    expect(defaults["checkout-branch"]).toBe(true)
    expect(defaults["checkout-detach"]).toBe(true)
    expect(defaults["list-branches"]).toBe(false)
    expect(defaults["rev-parse"]).toBe(false)
    expect(defaults["log-commits"]).toBe(false)
  })

  it("always shows failed tasks even when muted", () => {
    const visibility = { ...defaultTaskVisibility(), "pull": false }

    expect(isTaskVisible({ kind: "pull", status: "Failed" }, visibility)).toBe(true)
    expect(isTaskVisible({ kind: "pull", status: "Running" }, visibility)).toBe(false)
    expect(isTaskVisible({ kind: "log-commits", status: "Failed" }, visibility)).toBe(true)
    expect(isTaskVisible({ kind: "log-commits", status: "Succeded" }, visibility)).toBe(false)
  })

  it("shows unknown kinds instead of hiding them", () => {
    expect(isTaskVisible({ kind: "future-kind", status: "Running" }, {})).toBe(true)
  })

  it("persists overrides in localStorage", () => {
    saveTaskVisibility({ ...defaultTaskVisibility(), "pull": false })

    expect(loadTaskVisibility()["pull"]).toBe(false)
    expect(loadTaskVisibility()["clone"]).toBe(true)
  })

  it("updates every subscriber when toggling", () => {
    const first = renderHook(() => useTaskVisibility())
    const second = renderHook(() => useTaskVisibility())

    act(() => {
      first.result.current[1]("pull", false)
    })

    expect(first.result.current[0]["pull"]).toBe(false)
    expect(second.result.current[0]["pull"]).toBe(false)
    expect(loadTaskVisibility()["pull"]).toBe(false)
  })
})

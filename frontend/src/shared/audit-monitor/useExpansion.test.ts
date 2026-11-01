import { act, renderHook } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { useExpansion } from "./useExpansion.ts"

beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

it("persists toggles through the storage service and restores them on remount", () => {
  const set = vi.spyOn(localStorage, "set")
  const path = [40, "maintainability", "manager", "modularity"]
  const { result, unmount } = renderHook(() => useExpansion(path))
  expect(result.current[0]).toBe(true)
  expect(set).not.toHaveBeenCalled()
  act(() => result.current[1]())
  expect(set).toHaveBeenCalledWith(`audits.expansion:${JSON.stringify(path)}`, false)
  unmount()
  const restored = renderHook(() => useExpansion(path))
  expect(restored.result.current[0]).toBe(false)
  act(() => restored.result.current[1]())
  expect(restored.result.current[0]).toBe(true)
  expect(localStorage.get(`audits.expansion:${JSON.stringify(path)}`, false)).toBe(true)
})

it("isolates audits, pipelines and parent branches even when the mounted view changes identity", () => {
  const original = [40, "maintainability", "manager", "modularity"]
  const { result, rerender } = renderHook(({ path }) => useExpansion(path), { initialProps: { path: original } })
  act(() => result.current[1]())
  for (const path of [[41, ...original.slice(1)], [40, "security", "manager", "modularity"],
    [40, "maintainability", "other-manager", "modularity"]]) {
    rerender({ path })
    expect(result.current[0]).toBe(true)
  }
  rerender({ path: original })
  expect(result.current[0]).toBe(false)
})

it("honors defaults and ignores malformed or non-boolean saved values", () => {
  const key = "audits.expansion:[40]"
  for (const raw of ["{broken", "null", '"false"', "{}", "[]", "1"]) {
    window.localStorage.setItem(key, raw)
    const { result, unmount } = renderHook(() => useExpansion([40], false))
    expect(result.current[0]).toBe(false)
    unmount()
  }
  localStorage.set(key, true)
  const { result } = renderHook(() => useExpansion([40], false))
  expect(result.current[0]).toBe(true)
})

it("keeps toggles usable when browser storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("unavailable") })
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("unavailable") })
  const { result } = renderHook(() => useExpansion([40]))
  act(() => result.current[1]())
  expect(result.current[0]).toBe(false)
  act(() => result.current[1]())
  expect(result.current[0]).toBe(true)
})

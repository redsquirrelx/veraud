import { describe, expect, it } from "vitest"
import { LocalStorage } from "./LocalStorage.ts"

describe("LocalStorage", () => {
  it("returns the fallback for missing keys", () => {
    const storage = new LocalStorage()

    expect(storage.get("missing-key", true)).toBe(true)
  })

  it("round-trips stored values", () => {
    const storage = new LocalStorage()

    storage.set("sidebar.expanded", false)

    expect(storage.get("sidebar.expanded", true)).toBe(false)
  })

  it("falls back on corrupt values", () => {
    const storage = new LocalStorage()
    window.localStorage.setItem("broken", "{not-json")

    expect(storage.get("broken", "fallback")).toBe("fallback")
  })

  it("removes stored values", () => {
    const storage = new LocalStorage()
    storage.set("temp", 1)
    storage.remove("temp")

    expect(storage.get("temp", 0)).toBe(0)
  })
})

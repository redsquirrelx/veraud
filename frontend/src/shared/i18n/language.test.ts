import { beforeEach, describe, expect, it } from "vitest"
import {
  getStoredLanguage,
  isSupportedLanguage,
  languageStorageKey,
  normalizeLanguageTag,
  resolveInitialLanguage,
  setDocumentLanguage,
  setStoredLanguage,
} from "./language.ts"

function setBrowser(languages: string[] | undefined, language: string | undefined) {
  Object.defineProperty(window.navigator, "languages", { value: languages, configurable: true, writable: true })
  Object.defineProperty(window.navigator, "language", { value: language, configurable: true, writable: true })
}

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.lang = "en"
})

describe("normalizeLanguageTag", () => {
  it.each([
    ["es", "es"],
    ["en", "en"],
    ["es-CL", "es"],
    ["es_AR", "es"],
    ["en-US", "en"],
    ["EN", "en"],
    [" es ", "es"],
  ])("normalizes %s to %s", (input, expected) => {
    expect(normalizeLanguageTag(input)).toBe(expected)
  })

  it.each([["fr"], ["de-DE"], [""], ["  "], [null], [undefined]])("rejects %s", (input) => {
    expect(normalizeLanguageTag(input)).toBeNull()
  })

  it("validates supported languages", () => {
    expect(isSupportedLanguage("es")).toBe(true)
    expect(isSupportedLanguage("en")).toBe(true)
    expect(isSupportedLanguage("fr")).toBe(false)
    expect(isSupportedLanguage(null)).toBe(false)
    expect(isSupportedLanguage({ id: "es" })).toBe(false)
  })
})

describe("stored language", () => {
  it("round-trips through infrastructure storage", () => {
    setStoredLanguage("es")
    expect(getStoredLanguage()).toBe("es")
    expect(window.localStorage.getItem(languageStorageKey)).toBe(JSON.stringify("es"))
  })

  it.each([["fr"], ["es-CL"], [""]])("discards unsupported stored value %s", (value) => {
    window.localStorage.setItem(languageStorageKey, JSON.stringify(value))
    expect(getStoredLanguage()).toBeNull()
  })

  it("discards non-string and broken stored values", () => {
    window.localStorage.setItem(languageStorageKey, JSON.stringify({ id: "es" }))
    expect(getStoredLanguage()).toBeNull()
    window.localStorage.setItem(languageStorageKey, "{broken")
    expect(getStoredLanguage()).toBeNull()
  })
})

describe("resolveInitialLanguage", () => {
  it("prefers the stored language over the browser language", () => {
    setStoredLanguage("es")
    setBrowser(["en-US"], "en-US")
    expect(resolveInitialLanguage()).toBe("es")
  })

  it("uses the first supported browser language", () => {
    setBrowser(["fr", "es-CL", "en-US"], "fr")
    expect(resolveInitialLanguage()).toBe("es")
  })

  it("discards an unsupported stored value and uses the browser language", () => {
    window.localStorage.setItem(languageStorageKey, JSON.stringify("fr"))
    setBrowser(["es"], "es")
    expect(resolveInitialLanguage()).toBe("es")
  })

  it("falls back to English when nothing is supported", () => {
    setBrowser(["fr", "de"], "fr")
    expect(resolveInitialLanguage()).toBe("en")
  })

  it("falls back to English without browser information", () => {
    setBrowser(undefined, undefined)
    expect(resolveInitialLanguage()).toBe("en")
  })
})

describe("setDocumentLanguage", () => {
  it.each([
    ["es", "es"],
    ["es-CL", "es"],
    ["en-US", "en"],
    ["fr", "en"],
  ])("maps %s to <html lang=%s>", (input, expected) => {
    setDocumentLanguage(input)
    expect(document.documentElement.lang).toBe(expected)
  })
})

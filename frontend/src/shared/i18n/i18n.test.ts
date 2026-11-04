import { beforeAll, beforeEach, describe, expect, it } from "vitest"
import { changeLanguage, i18n, initializeI18n } from "./index.ts"
import { languageStorageKey, setStoredLanguage } from "./language.ts"
import { resources } from "./resources.ts"

function setBrowser(languages: string[] | undefined, language: string | undefined) {
  Object.defineProperty(window.navigator, "languages", { value: languages, configurable: true, writable: true })
  Object.defineProperty(window.navigator, "language", { value: language, configurable: true, writable: true })
}

beforeAll(async () => {
  await initializeI18n()
})

beforeEach(() => {
  window.localStorage.clear()
})

describe("i18n resources", () => {
  it("keeps matching translation keys across languages", () => {
    function keys(value: object, prefix = ""): string[] {
      return Object.entries(value).flatMap(([key, entry]) => {
        const path = prefix ? `${prefix}.${key}` : key
        return typeof entry === "object" && entry !== null ? keys(entry, path) : [path]
      }).sort()
    }

    expect(keys(resources.es)).toEqual(keys(resources.en))
  })

  it("interpolates values and selects plural forms in both languages", () => {
    const en = i18n.getFixedT("en", ["projects", "common"])
    const es = i18n.getFixedT("es", ["projects", "common"])

    expect(en("projects:registration.success", { name: "Veraud" })).toBe("Project Veraud was registered successfully.")
    expect(es("projects:registration.success", { name: "Veraud" })).toBe("El proyecto Veraud se registró correctamente.")
    expect(en("projects:selectedCount", { count: 1 })).toBe("1 project selected")
    expect(en("projects:selectedCount", { count: 2 })).toBe("2 projects selected")
    expect(es("projects:selectedCount", { count: 1 })).toBe("1 proyecto seleccionado")
    expect(es("projects:selectedCount", { count: 2 })).toBe("2 proyectos seleccionados")
    expect(en("projects:qualityAudits.report.sourceReferences", { count: 0, formattedCount: "0" })).toBe("Source references (0)")
    expect(en("projects:qualityAudits.report.sourceReferences", { count: 1, formattedCount: "1" })).toBe("Source reference (1)")
    expect(es("projects:qualityAudits.report.sourceReferences", { count: 2, formattedCount: "2" })).toBe("Referencias de origen (2)")
    expect(en("common:testPages.controls.modelCount", { count: 1 })).toBe("1 model")
    expect(es("common:testPages.controls.modelCount", { count: 3 })).toBe("3 modelos")
    expect(es("projects:qualityAudits.requirements.help", { minimum: 1, maximum: 100 }))
      .toContain("1–100")
  })

  it("resolves regional variants and falls back to English for unsupported languages", () => {
    expect(i18n.getFixedT("es-CL", "common")("actions.save")).toBe("Guardar")
    expect(i18n.getFixedT("en-US", "common")("actions.save")).toBe("Save")
    expect(i18n.getFixedT("fr", "common")("actions.save")).toBe("Save")
  })

  it("prefers the stored language over the browser language on initialize", async () => {
    setStoredLanguage("es")
    setBrowser(["en-US"], "en-US")
    await initializeI18n()
    expect(i18n.language).toBe("es")
    expect(document.documentElement.lang).toBe("es")
  })

  it("falls back to English for unsupported stored and browser languages", async () => {
    window.localStorage.setItem(languageStorageKey, JSON.stringify("fr"))
    setBrowser(["de"], "de")
    await initializeI18n()
    expect(i18n.language).toBe("en")
    expect(document.documentElement.lang).toBe("en")
  })

  it("persists explicit choices and syncs the document language", async () => {
    await changeLanguage("es")
    expect(window.localStorage.getItem(languageStorageKey)).toBe(JSON.stringify("es"))
    expect(document.documentElement.lang).toBe("es")
    expect(i18n.getFixedT("es", "common")("actions.save")).toBe("Guardar")

    await changeLanguage("en")
    expect(window.localStorage.getItem(languageStorageKey)).toBe(JSON.stringify("en"))
    expect(document.documentElement.lang).toBe("en")
  })
})

import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { fallbackLanguage, supportedLanguages, type SupportedLanguage } from "./resources.ts"

export const languageStorageKey = "settings.language"

export function isSupportedLanguage(value: unknown): value is SupportedLanguage {
  return typeof value === "string" && (supportedLanguages as readonly string[]).includes(value)
}

export function normalizeLanguageTag(tag: string | null | undefined): SupportedLanguage | null {
  if (typeof tag !== "string") {
    return null
  }
  const base = tag.trim().toLowerCase().split(/[-_]/)[0]
  return isSupportedLanguage(base) ? base : null
}

export function getBrowserLanguages(): string[] {
  if (typeof navigator === "undefined") {
    return []
  }
  if (Array.isArray(navigator.languages) && navigator.languages.length > 0) {
    return navigator.languages.filter((entry): entry is string => typeof entry === "string")
  }
  return typeof navigator.language === "string" ? [navigator.language] : []
}

export function getBrowserLanguage(): SupportedLanguage | null {
  for (const tag of getBrowserLanguages()) {
    const normalized = normalizeLanguageTag(tag)
    if (normalized !== null) {
      return normalized
    }
  }
  return null
}

export function getStoredLanguage(): SupportedLanguage | null {
  const stored = localStorage.get<unknown>(languageStorageKey, null)
  return isSupportedLanguage(stored) ? stored : null
}

export function setStoredLanguage(language: SupportedLanguage): void {
  localStorage.set(languageStorageKey, language)
}

export function resolveInitialLanguage(): SupportedLanguage {
  return getStoredLanguage() ?? getBrowserLanguage() ?? fallbackLanguage
}

export function setDocumentLanguage(language: string): void {
  if (typeof document === "undefined") {
    return
  }
  document.documentElement.lang = normalizeLanguageTag(language) ?? fallbackLanguage
}

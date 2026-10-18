import { i18n } from "./index.ts"
import { normalizeLanguageTag } from "./language.ts"
import { fallbackLanguage } from "./resources.ts"

// Active locale for Intl formatters. Components re-render on language change
// through react-i18next, so call these during render, never at module scope:
// a module-level Intl instance would freeze the locale of the first render.
export function getLocale(): string {
  return normalizeLanguageTag(i18n.language) ?? fallbackLanguage
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(getLocale(), options).format(value)
}

export function formatDate(value: string | number | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(getLocale(), options).format(new Date(value))
}

export function formatDateTime(value: string | number | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(getLocale(), { dateStyle: "medium", timeStyle: "short", ...options }).format(new Date(value))
}

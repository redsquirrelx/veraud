import i18next from "i18next"
import { initReactI18next } from "react-i18next"
import { defaultNS, fallbackLanguage, resources, supportedLanguages, type SupportedLanguage } from "./resources.ts"
import { normalizeLanguageTag, resolveInitialLanguage, setDocumentLanguage, setStoredLanguage } from "./language.ts"

// Default i18next singleton: `useTranslation` works with or without an
// explicit provider, which keeps component tests independent of providers.
export const i18n = i18next
let documentLanguageSyncAttached = false

// Resolve the initial language (stored preference, browser, fallback) and
// initialize before rendering. Safe to call more than once (tests, remounts).
export async function initializeI18n(language?: string) {
  const resolved = (language ? normalizeLanguageTag(language) : null) ?? resolveInitialLanguage()

  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      resources,
      lng: resolved,
      fallbackLng: fallbackLanguage,
      supportedLngs: [...supportedLanguages],
      load: "languageOnly",
      ns: Object.keys(resources.en),
      defaultNS,
      interpolation: {
        // React escapes interpolated text when rendering.
        escapeValue: false,
      },
      react: {
        useSuspense: false,
      },
    })
  } else if (i18n.language !== resolved) {
    await i18n.changeLanguage(resolved)
  }

  setDocumentLanguage(resolved)
  if (!documentLanguageSyncAttached) {
    i18n.on("languageChanged", setDocumentLanguage)
    documentLanguageSyncAttached = true
  }

  return i18n
}

// Persist an explicit user choice and apply it without reloading.
export async function changeLanguage(language: SupportedLanguage) {
  setStoredLanguage(language)
  setDocumentLanguage(language)
  if (!i18n.isInitialized) {
    await initializeI18n(language)
    return i18n
  }
  await i18n.changeLanguage(language)
  return i18n
}

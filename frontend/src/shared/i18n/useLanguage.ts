import { useCallback } from "react"
import { useTranslation } from "react-i18next"
import { changeLanguage } from "./index.ts"
import { fallbackLanguage, supportedLanguages, type SupportedLanguage } from "./resources.ts"
import { normalizeLanguageTag } from "./language.ts"

export function useLanguage() {
  const { i18n } = useTranslation()
  const language = normalizeLanguageTag(i18n.language) ?? fallbackLanguage

  const selectLanguage = useCallback((next: SupportedLanguage) => {
    void changeLanguage(next)
  }, [])

  return { language, selectLanguage, supportedLanguages }
}

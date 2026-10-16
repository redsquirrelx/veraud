import { useTranslation } from "react-i18next"
import { RadioButton } from "../../shared/ui-kit/index.ts"
import { isSupportedLanguage } from "../../shared/i18n/language.ts"
import { type SupportedLanguage } from "../../shared/i18n/resources.ts"
import { useLanguage } from "../../shared/i18n/useLanguage.ts"

const languageLabelKeys = {
  es: "preferences.languages.es",
  en: "preferences.languages.en",
} as const satisfies Record<SupportedLanguage, `preferences.languages.${SupportedLanguage}`>

export function LanguageSelector() {
  const { t } = useTranslation("settings")
  const { language, selectLanguage, supportedLanguages } = useLanguage()

  return (
    <>
      <span className="label">{t("preferences.language")}</span>
      <p className="settings-hint">{t("preferences.languageHint")}</p>
      <div className="settings-language-options" role="radiogroup" aria-label={t("preferences.language")}>
        {supportedLanguages.map((option) => (
          <RadioButton
            key={option}
            label={t(languageLabelKeys[option])}
            name="language"
            value={option}
            checked={language === option}
            onChange={(value) => {
              if (isSupportedLanguage(value)) {
                selectLanguage(value)
              }
            }}
          />
        ))}
      </div>
    </>
  )
}

import { useTranslation } from "react-i18next"
import { Button, TextInput } from "../../shared/ui-kit/index.ts"
import type { useRegisterProject } from "./useRegisterProject.ts"
import "./ProjectRegistrationForm.css"

type Registration = ReturnType<typeof useRegisterProject>

export function ProjectRegistrationForm({ registration }: { registration: Registration }) {
  const { t } = useTranslation("projects")
  const canSubmit = registration.url.trim() !== "" && !registration.cooling

  return (
    <div className="registration-form">
      <TextInput
        value={registration.url}
        placeholder={t("registration.urlPlaceholder")}
        onChange={registration.changeUrl}
      />
      <Button loading={registration.cooling} loadingText={t("registration.loadingText")} disabled={!canSubmit} onClick={() => void registration.register()}>
        {t("registration.submit")}
      </Button>
    </div>
  )
}

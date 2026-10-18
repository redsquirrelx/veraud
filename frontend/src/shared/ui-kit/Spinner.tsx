import { useTranslation } from "react-i18next"
import "./Spinner.css"

interface SpinnerProps {
  size?: number
  tone?: "light" | "dark"
}

export function Spinner({ size = 16, tone = "dark" }: SpinnerProps) {
  const { t } = useTranslation("common")
  return (
    <span
      className={`ui-spinner ui-spinner-${tone}`}
      style={{ width: size, height: size }}
      role="status"
      aria-label={t("ui.loading")}
    />
  )
}

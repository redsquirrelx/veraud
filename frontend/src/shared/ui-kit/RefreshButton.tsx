import { useTranslation } from "react-i18next"
import { RefreshIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import "./RefreshButton.css"

interface RefreshButtonProps {
  loading?: boolean
  onClick: () => void
}

export function RefreshButton({ loading = false, onClick }: RefreshButtonProps) {
  const { t } = useTranslation("common")
  return (
    <button
      type="button"
      className="ui-refresh-button"
      aria-label={t("ui.refresh")}
      disabled={loading}
      onClick={onClick}
    >
      {loading ? <Spinner size={14} /> : <RefreshIcon />}
    </button>
  )
}

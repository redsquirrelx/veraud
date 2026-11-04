import { useTranslation } from "react-i18next"
import { RefreshIcon } from "./icons.tsx"
import { Spinner } from "./Spinner.tsx"
import { IconButton } from "./IconButton.tsx"

interface RefreshButtonProps {
  loading?: boolean
  onClick: () => void
}

export function RefreshButton({ loading = false, onClick }: RefreshButtonProps) {
  const { t } = useTranslation("common")
  return (
    <IconButton
      variant="outline"
      size="md"
      ariaLabel={t("ui.refresh")}
      disabled={loading}
      onClick={onClick}
    >
      {loading ? <Spinner size={14} /> : <RefreshIcon />}
    </IconButton>
  )
}

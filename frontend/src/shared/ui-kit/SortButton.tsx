import { useTranslation } from "react-i18next"
import { ArrowDownIcon, ArrowUpIcon } from "./icons.tsx"
import "./SortButton.css"

interface SortButtonProps {
  direction: "asc" | "desc"
  onToggle: () => void
}

export function SortButton({ direction, onToggle }: SortButtonProps) {
  const { t } = useTranslation("common")
  const label = direction === "asc" ? t("ui.sortDescending") : t("ui.sortAscending")
  return (
    <button
      type="button"
      className="ui-sort-button"
      aria-label={label}
      title={label}
      onClick={onToggle}
    >
      {direction === "asc" ? <ArrowUpIcon /> : <ArrowDownIcon />}
    </button>
  )
}

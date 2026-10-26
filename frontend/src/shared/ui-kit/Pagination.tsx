import { useTranslation } from "react-i18next"
import { ChevronLeftIcon, ChevronRightIcon } from "./icons.tsx"
import { IconButton } from "./IconButton.tsx"
import "./Pagination.css"

interface PaginationProps {
  page: number
  pageCount: number
  onChange: (page: number) => void
  label?: string
}

export function Pagination({ page, pageCount, onChange, label }: PaginationProps) {
  const { t } = useTranslation("common")
  if (pageCount <= 1) {
    return null
  }

  return (
    <nav className="ui-pagination" aria-label={label ?? t("ui.pagination.pages")}>
      <IconButton
        variant="pagination"
        size="sm"
        className="ui-pagination-button"
        ariaLabel={t("ui.pagination.previousPage")}
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        <ChevronLeftIcon />
      </IconButton>
      <span className="ui-pagination-label">
        {t("ui.pagination.pageOf", { page, pageCount })}
      </span>
      <IconButton
        variant="pagination"
        size="sm"
        className="ui-pagination-button"
        ariaLabel={t("ui.pagination.nextPage")}
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        <ChevronRightIcon />
      </IconButton>
    </nav>
  )
}

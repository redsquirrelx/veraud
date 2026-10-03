import { ChevronLeftIcon, ChevronRightIcon } from "./icons.tsx"
import "./Pagination.css"

interface PaginationProps {
  page: number
  pageCount: number
  onChange: (page: number) => void
}

export function Pagination({ page, pageCount, onChange }: PaginationProps) {
  if (pageCount <= 1) {
    return null
  }

  return (
    <nav className="ui-pagination" aria-label="Projects pages">
      <button
        type="button"
        className="ui-pagination-button"
        aria-label="Previous page"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        <ChevronLeftIcon />
      </button>
      <span className="ui-pagination-label">
        Page {page} of {pageCount}
      </span>
      <button
        type="button"
        className="ui-pagination-button"
        aria-label="Next page"
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
      >
        <ChevronRightIcon />
      </button>
    </nav>
  )
}

import { ArrowDownIcon, ArrowUpIcon } from "./icons.tsx"
import "./SortButton.css"

interface SortButtonProps {
  direction: "asc" | "desc"
  onToggle: () => void
}

export function SortButton({ direction, onToggle }: SortButtonProps) {
  return (
    <button
      type="button"
      className="ui-sort-button"
      aria-label={direction === "asc" ? "Sort descending" : "Sort ascending"}
      title={direction === "asc" ? "Sort descending" : "Sort ascending"}
      onClick={onToggle}
    >
      {direction === "asc" ? <ArrowUpIcon /> : <ArrowDownIcon />}
    </button>
  )
}

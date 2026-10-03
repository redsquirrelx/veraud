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
      onClick={onToggle}
    >
      <span aria-hidden="true">Γëí</span>
      <span>ORDEN: {direction === "asc" ? "Γåæ" : "Γåô"}</span>
    </button>
  )
}

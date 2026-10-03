import { Spinner } from "./Spinner.tsx"
import "./RefreshButton.css"

interface RefreshButtonProps {
  loading?: boolean
  onClick: () => void
}

export function RefreshButton({ loading = false, onClick }: RefreshButtonProps) {
  return (
    <button
      type="button"
      className="ui-refresh-button"
      aria-label="Refresh"
      disabled={loading}
      onClick={onClick}
    >
      {loading ? <Spinner size={14} /> : <span aria-hidden="true">Γå╗</span>}
    </button>
  )
}

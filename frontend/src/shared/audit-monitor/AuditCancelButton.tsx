import { Spinner, Tooltip, XIcon } from "../ui-kit/index.ts"
import { useMonitorLabels } from "./monitorLabels.ts"

/** Compact action sharing the repository badge surface. */
export function AuditCancelButton({ onClick, pending = false }: { onClick: () => void, pending?: boolean }) {
  const labels = useMonitorLabels()
  return <Tooltip content={pending ? labels.cancelling : labels.cancelAudit} placement="left">
    {(props) => <button {...props} type="button" className="audit-status-project audit-cancel-button"
      aria-label={pending ? labels.cancelling : labels.cancelAudit} disabled={pending} aria-busy={pending} onClick={onClick}>
      {pending ? <Spinner size={12} tone="light" /> : <XIcon size={12} />}
    </button>}
  </Tooltip>
}

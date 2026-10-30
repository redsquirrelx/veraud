import { Tooltip, XIcon } from "../ui-kit/index.ts"
import { useMonitorLabels } from "./monitorLabels.ts"

/** Compact action sharing the repository badge surface. */
export function AuditCancelButton({ onClick }: { onClick: () => void }) {
  const labels = useMonitorLabels()
  return <Tooltip content={labels.cancelAudit} placement="left">
    {(props) => <button {...props} type="button" className="audit-status-project audit-cancel-button"
      aria-label={labels.cancelAudit} onClick={onClick}>
      <XIcon size={12} />
    </button>}
  </Tooltip>
}

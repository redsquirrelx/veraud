import { useId, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "react-router-dom"
import { ArrowRightIcon, Badge, Card, ChevronDownIcon, FolderIcon } from "../ui-kit/index.ts"
import { AuditStatusView } from "./AuditStatusView.tsx"
import { auditProgress, progressText, stateLabelKey, stateTone, type AuditStatusModel } from "./auditStatus.ts"
import "./AuditStatusDisclosure.css"

export interface AuditStatusDisclosureProps {
  audit: AuditStatusModel
  /** Callers decide the initial state: a finished audit is usually folded. */
  defaultExpanded?: boolean
  evidenceLinks?: boolean
}

/** One audit as a summary row that reveals its pipelines and agents. The
 *  project link stays outside the toggle: a link nested in a button is invalid
 *  and swallows the toggle's own activation. */
export function AuditStatusDisclosure({ audit, defaultExpanded = true, evidenceLinks = false }: AuditStatusDisclosureProps) {
  const { t } = useTranslation("projects")
  const regionId = useId()
  const [expanded, setExpanded] = useState(defaultExpanded)
  const repository = audit.project ? `${audit.project.repositoryOwner}/${audit.project.repositoryName}` : null

  return (
    <Card>
      <div className="audit-disclosure" data-state={audit.state}>
        <div className="audit-disclosure-head">
          {audit.project && <Link className="audit-status-project" to={`/projects/${audit.project.id}/audits`}
            aria-label={t("auditStatus.openProject", { repository })}>
            <FolderIcon size={13} />
            <span className="mono">{repository}</span>
            <ArrowRightIcon size={12} />
          </Link>}
          <button
            type="button"
            className="audit-disclosure-toggle"
            aria-expanded={expanded}
            aria-controls={regionId}
            // Explicit name: the row has no whitespace between its parts, so a
            // name taken from the contents would read "Audit #40Completed…".
            aria-label={t("auditStatus.toggleLabel", {
              id: t("auditStatus.title", { id: audit.id }),
              state: t(stateLabelKey(audit.state)),
              progress: progressText(t, auditProgress(audit)),
            })}
            onClick={() => setExpanded((current) => !current)}
          >
            <span className="audit-disclosure-line">
              <span className="mono audit-disclosure-id">{t("auditStatus.title", { id: audit.id })}</span>
              <span className="audit-disclosure-chevron" data-expanded={expanded} aria-hidden="true">
                <ChevronDownIcon size={12} />
              </span>
            </span>
            <span className="audit-disclosure-line">
              <Badge tone={stateTone(audit.state)}>{t(stateLabelKey(audit.state))}</Badge>
              <span className="label">{progressText(t, auditProgress(audit))}</span>
              {audit.reportAvailable && <Badge tone="neutral">{t("auditStatus.reportAvailable")}</Badge>}
            </span>
          </button>
        </div>
        <div
          id={regionId}
          className="audit-disclosure-detail"
          data-expanded={expanded}
          aria-hidden={!expanded}
          inert={!expanded}
        >
          <div className="audit-disclosure-detail-inner">
            {/* No summary: the row above already carries the identity. */}
            <AuditStatusView audit={audit} bare summary={false} evidenceLinks={evidenceLinks} />
          </div>
        </div>
      </div>
    </Card>
  )
}

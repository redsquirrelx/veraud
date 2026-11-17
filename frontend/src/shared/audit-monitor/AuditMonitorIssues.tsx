import { useCallback, useEffect, useState } from "react"
import { createPortal } from "react-dom"
import { useTranslation } from "react-i18next"
import { requestJson } from "../../infrastructure/http-client/httpClient.ts"
import { Spinner, Button, DotsIcon, IconButton, Modal } from "../ui-kit/index.ts"
import { auditIssuesFromReport, type AuditIssue } from "./auditIssues.ts"
import type { AuditStatusModel } from "./auditStatus.ts"
import "./AuditMonitorIssues.css"

type IssuesState = { status: "loading" } | { status: "error" } | { status: "ready", issues: AuditIssue[] }

/** Fetches the published annexes lazily, only when the operator asks for the
 * reason; audits whose report does not exist yet fall back to an error note. */
function IssuesBody({ projectId, auditId }: { projectId: number, auditId: number }) {
  const { t } = useTranslation("projects")
  const [state, setState] = useState<IssuesState>({ status: "loading" })
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let ignore = false
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      if (ignore) return
      ignore = true
      controller.abort()
      setState({ status: "error" })
    }, 15_000)
    requestJson<unknown>(`/api/projects/${projectId}/audits/${auditId}/execution-issues`,
      "Could not load the report detail", { signal: controller.signal })
      .then((body) => {
        if (!ignore) setState({ status: "ready", issues: auditIssuesFromReport(body) })
      })
      .catch(() => { if (!ignore) setState({ status: "error" }) })
      .finally(() => window.clearTimeout(timeout))
    return () => { ignore = true; window.clearTimeout(timeout); controller.abort() }
  }, [projectId, auditId, revision])

  if (state.status === "loading") return <div className="audit-issues-status"><Spinner /></div>
  if (state.status === "error") return <div className="audit-issues-status" role="alert">
    <p>{t("auditStatus.issues.loadFailed")}</p>
    <Button variant="secondary" onClick={() => { setState({ status: "loading" }); setRevision((value) => value + 1) }}>{t("auditStatus.issues.retry")}</Button>
  </div>
  if (state.issues.length === 0) return <p className="label">{t("auditStatus.issues.empty")}</p>
  return <ul className="audit-issues-list">
    {state.issues.map((issue) => <li key={`${issue.agentId}:${issue.invocationId ?? ""}:${issue.terminationReason ?? ""}`}
      className="audit-issue">
      <div className="audit-issue-head"><strong className="mono">{issue.agentId}</strong>
        {issue.terminationReason && <code className="audit-issue-termination">{issue.terminationReason}</code>}
      </div>
      {issue.explanation && <p className="audit-issue-explanation">{issue.explanation}</p>}
      {issue.incidents.length > 0 && <ul className="audit-issue-incidents">
        {issue.incidents.map((incident) => <li key={incident}>{incident}</li>)}
      </ul>}
      {issue.diagnostics.length > 0 && <details className="audit-issue-diagnostics">
        <summary>{t("auditStatus.issues.diagnostics", { count: issue.diagnostics.length })}</summary>
        <pre>{issue.diagnostics.join("\n")}</pre>
      </details>}
    </li>)}
  </ul>
}

/** Small affordance for audits that finished with a partial/failed verdict:
 * opens a modal with the reasons recorded in the published report. */
export function AuditMonitorIssues({ audit }: { audit: AuditStatusModel }) {
  const { t } = useTranslation("projects")
  const [open, setOpen] = useState(false)
  const projectId = audit.project && audit.project.id > 0 ? audit.project.id : null
  const close = useCallback(() => setOpen(false), [])
  if (!projectId || (audit.state !== "partial" && audit.state !== "failed")) return null
  return <>
    <IconButton variant="ghost" size="sm" ariaLabel={t("auditStatus.issues.view")} title={t("auditStatus.issues.view")}
      onClick={() => setOpen(true)}>
      <DotsIcon size={14} />
    </IconButton>
    {open && createPortal(<div onKeyDown={(event) => {
      if (event.key === "Escape") { event.stopPropagation(); close() }
    }}>
      <Modal open label={t("auditStatus.issues.title")} title={t("auditStatus.issues.title")} size="wide" onClose={close}>
        <IssuesBody key={`${projectId}:${audit.id}`} projectId={projectId} auditId={audit.id} />
      </Modal>
    </div>, document.body)}
  </>
}

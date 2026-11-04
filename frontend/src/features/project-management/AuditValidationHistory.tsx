import { useId, useState, type ReactNode } from "react"
import { useTranslation } from "react-i18next"
import { formatDateTime } from "../../shared/i18n/format.ts"
import { Badge, Button, ChevronDownIcon, ChevronRightIcon } from "../../shared/ui-kit/index.ts"
import type { QualityAuditSummary } from "./qualityAuditApi.ts"
import { NewRevalidationModal } from "./NewRevalidationModal.tsx"
import { AuditRevalidationDetail } from "./AuditRevalidationDetail.tsx"
import "./AuditValidationHistory.css"

export interface AuditRevalidation {
  id: string
  /** null derives from Initial Audit; otherwise references another revalidation. */
  parentId: string | null
  createdAt: string
  commitHash: string
}

function timestamp(value: string): number {
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function ValidationDate({ value }: { value: string }) {
  return Number.isNaN(new Date(value).getTime()) ? null : <time dateTime={value}>{formatDateTime(value)}</time>
}

export function AuditValidationHistory({ audit, revalidations = [], preview = false }: {
  audit: Pick<QualityAuditSummary, "createdAt" | "startedAt">
  revalidations?: readonly AuditRevalidation[]
  preview?: boolean
}) {
  const { i18n } = useTranslation("projects")
  const [revalidationBase, setRevalidationBase] = useState<{ id: string, commitHash: string, name: string } | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string | null>>(() => new Set())
  const [detail, setDetail] = useState<(AuditRevalidation & { number: number }) | null>(null)
  const treeId = useId()
  const spanish = i18n.resolvedLanguage?.startsWith("es")
  const title = spanish ? "Historial de validación" : "Validation history"
  const labels = spanish
    ? { create: "+ Nueva revalidación", detail: "Ver detalle", commit: "Commit" }
    : { create: "+ New revalidation", detail: "View details", commit: "Commit" }
  // Number globally by creation time, independently of where a node sits in the tree.
  const ordered = [...revalidations].sort((a, b) => timestamp(a.createdAt) - timestamp(b.createdAt) || a.id.localeCompare(b.id))
  const children = new Map<string | null, Array<AuditRevalidation & { number: number }>>()
  ordered.forEach((item, index) => {
    const siblings = children.get(item.parentId) ?? []
    siblings.push({ ...item, number: index + 1 })
    children.set(item.parentId, siblings)
  })

  function branchId(parentId: string | null) {
    return `${treeId}-${parentId === null ? "root" : `node-${parentId}`}-children`
  }

  function marker(parentId: string | null, content: ReactNode, name: string) {
    if (!children.has(parentId)) return <span className="audit-validation-marker" aria-hidden="true">{content}</span>
    const closed = collapsed.has(parentId)
    const action = spanish ? closed ? "Mostrar revalidaciones de" : "Ocultar revalidaciones de"
      : closed ? "Show revalidations of" : "Hide revalidations of"
    return <button type="button" className="audit-validation-marker audit-validation-toggle"
      aria-label={`${action} ${name}`} aria-expanded={!closed} aria-controls={branchId(parentId)}
      onClick={() => setCollapsed((previous) => {
        const next = new Set(previous)
        if (next.has(parentId)) next.delete(parentId)
        else next.add(parentId)
        return next
      })}>
      <span aria-hidden="true">{content}</span>
      <span className="audit-validation-toggle-chevron" aria-hidden="true">{closed ? <ChevronRightIcon size={10} /> : <ChevronDownIcon size={10} />}</span>
    </button>
  }

  function branches(parentId: string | null) {
    const items = children.get(parentId)
    if (!items?.length) return null
    return <ol className="audit-validation-branches" id={branchId(parentId)} hidden={collapsed.has(parentId)}>
      {items.map((item) => <li key={item.id}>
        <div className="audit-validation-row" data-has-children={children.has(item.id) && !collapsed.has(item.id)} data-latest={!children.has(item.id)}>
          {marker(item.id, item.number, `Revalidation #${item.number}`)}
          <div className="audit-validation-node">
            <div className="audit-validation-node-content">
              <div className="audit-validation-node-heading">
                <strong>Revalidation #{item.number}</strong>
                {!children.has(item.id) && <Badge tone="success">Latest</Badge>}
              </div>
              <code className="audit-validation-commit" title={item.commitHash} aria-label={`${labels.commit}: ${item.commitHash}`}>{item.commitHash.slice(0, 7)}</code>
              <ValidationDate value={item.createdAt} />
            </div>
            <div className="audit-validation-actions">
              <Button variant="primary" onClick={() => setRevalidationBase({ id: item.id, commitHash: item.commitHash, name: `Revalidation #${item.number}` })}>{labels.create}</Button>
              <Button variant="secondary" onClick={() => setDetail(item)}>{labels.detail}</Button>
            </div>
          </div>
        </div>
        {branches(item.id)}
      </li>)}
    </ol>
  }

  if (detail) return <AuditRevalidationDetail revalidation={detail} onBack={() => setDetail(null)} />

  return <section className="audit-validation-history" aria-label={title}>
    <div className="audit-validation-heading">
      <h3>{title}</h3>
      {preview && <span className="label">{spanish ? "Datos de ejemplo" : "Sample data"}</span>}
    </div>
    <div className="audit-validation-tree">
      <ol className="audit-validation-root">
        <li>
          <div className="audit-validation-row audit-validation-initial" data-has-children={children.has(null) && !collapsed.has(null)}>
            {marker(null,
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M2 10h5m6 0h5" /><circle cx="10" cy="10" r="3" />
              </svg>, "Initial Audit")}
            <div className="audit-validation-node">
              <strong>Initial Audit</strong><ValidationDate value={audit.startedAt ?? audit.createdAt} />
            </div>
          </div>
          {branches(null)}
        </li>
      </ol>
    </div>
    {revalidationBase && <NewRevalidationModal key={revalidationBase.id} commitHash={revalidationBase.commitHash}
      revisionName={revalidationBase.name} onClose={() => setRevalidationBase(null)} />}
  </section>
}

// Layout-only example: deliberately independent of audit metadata and API responses.
const previewAudit = { createdAt: "2026-10-17T10:00:00Z", startedAt: "2026-10-17T10:05:00Z" }
const previewRevalidations: readonly AuditRevalidation[] = [
  { id: "demo-1", parentId: null, createdAt: "2026-10-18T09:00:00Z", commitHash: "c4e89f1b8a2d073e61f94c2b503a7d68e9f012bc" },
  { id: "demo-2", parentId: null, createdAt: "2026-10-18T14:30:00Z", commitHash: "7b2a9d4e03c165f8a94b2d7e610c3f85a9d024eb" },
  { id: "demo-3", parentId: "demo-1", createdAt: "2026-10-19T10:15:00Z", commitHash: "e91c3a7b5d204f86c3a19e7b60d52f48a9c013de" },
  { id: "demo-4", parentId: "demo-1", createdAt: "2026-10-20T11:00:00Z", commitHash: "2fa7c83d4e091b65a8c3f2d710e694b5c0a183df" },
  { id: "demo-5", parentId: "demo-2", createdAt: "2026-10-21T09:45:00Z", commitHash: "8d4b1a6c90e3f572b6a09c4d813e2f75a0b69c3d" },
  { id: "demo-6", parentId: "demo-3", createdAt: "2026-10-22T16:00:00Z", commitHash: "a63e9b2c71d04f85e3b6a109c5d728f4b0e193ac" },
  { id: "demo-7", parentId: "demo-6", createdAt: "2026-10-23T10:30:00Z", commitHash: "5c8f2d1a9b604e73c0f815a2d69b3e47a1c092fd" },
]

export function AuditValidationHistoryPreview() {
  return <AuditValidationHistory audit={previewAudit} revalidations={previewRevalidations} preview />
}

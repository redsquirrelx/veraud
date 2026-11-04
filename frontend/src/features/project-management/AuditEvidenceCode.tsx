import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button, CodeViewer, Spinner } from "../../shared/ui-kit/index.ts"
import { evidenceCodeLocation, evidenceFilePath, type AgentEvidence, type EvidenceSymbol } from "./auditAgentEvidence.ts"
import { useProjectFile } from "./useProjectFile.ts"
import { useAuditSourceFile } from "./useAuditSourceFile.ts"

export function AuditEvidenceCode({ evidence, projectId, auditId, repositoryName, recordedOnly = false, auditedCommit }: {
  evidence: AgentEvidence, projectId: number | null, auditId?: number, repositoryName?: string, recordedOnly?: boolean, auditedCommit?: string | null
}) {
  return recordedOnly ? <RecordedEvidenceCode evidence={evidence} projectId={projectId} auditId={auditId} auditedCommit={auditedCommit} repositoryName={repositoryName} />
    : <WorkingCopyEvidenceCode evidence={evidence} projectId={projectId} repositoryName={repositoryName} />
}

function RecordedEvidenceCode({ evidence, projectId, auditId, auditedCommit, repositoryName }: {
  evidence: AgentEvidence, projectId: number | null, auditId?: number, auditedCommit?: string | null, repositoryName?: string
}) {
  const { t } = useTranslation("auditEvidence")
  const [selection, setSelection] = useState<{ evidenceId: string, symbolId: string } | null>(null)
  const verified = Boolean(auditedCommit && evidence.commit && auditedCommit.toLowerCase() === evidence.commit.toLowerCase() && evidence.commitVerification !== "unverified")
  const mismatch = Boolean(auditedCommit && evidence.commit && auditedCommit.toLowerCase() !== evidence.commit.toLowerCase())
  const rangesUnverified = mismatch || evidence.commitVerification === "unverified"
  const path = evidenceFilePath(evidence.source, repositoryName)
  const source = useAuditSourceFile(projectId, auditId, path, auditedCommit)
  const content = source.file?.content ?? (verified ? evidence.content : null)
  const location = evidenceCodeLocation({ ...evidence, content, ...(source.file ? { kind: "file" } : {}) })
  const selectedId = selection?.evidenceId === evidence.id ? selection.symbolId : ""
  const count = content ? content.replace(/\n$/, "").split("\n").length : 0
  const lastLine = location.firstLine + count - 1
  // A bad/missing evidence range does not invalidate coordinates in a complete
  // Git file. Excerpts still require a reliable source-number mapping.
  const sourceCoordinatesKnown = source.file !== null || evidence.kind === "file"
    || (evidence.startLine !== null && evidence.endLine !== null && !location.unmapped)
  const rangeForSymbol = (symbol: EvidenceSymbol | undefined) => {
    if (rangesUnverified || !symbol || !content || !sourceCoordinatesKnown || symbol.startLine === null || symbol.endLine === null
      || symbol.endLine < symbol.startLine || symbol.startLine < location.firstLine || symbol.startLine > lastLine) return null
    const symbolPath = evidenceFilePath(symbol.source ?? evidence.source, repositoryName)
    if (!symbolPath || symbolPath !== evidenceFilePath(evidence.source, repositoryName)) return null
    return { from: symbol.startLine, to: Math.min(symbol.endLine, lastLine) }
  }
  const selectedSymbol = evidence.symbols?.find((symbol) => symbol.id === selectedId)
  const symbolRange = rangeForSymbol(selectedSymbol)
  const range = rangesUnverified ? null : selectedId ? symbolRange : location.range
  const symbolKind = (kind: string | null | undefined) => kind === "class" ? t("symbolClass") : kind === "function" ? t("symbolFunction")
    : kind === "method" ? t("symbolMethod") : kind ?? t("notRecorded")
  const extension = evidence.source?.split(".").pop()?.toLowerCase() ?? ""
  const language = ({ tsx: "ts", jsx: "js" } as Record<string, string>)[extension] ?? extension
  return <>
    {evidence.symbolIds.length > 0 && <div className="audit-evidence-symbol-select">
      <label>{t("symbolDetails")}
        <select value={selectedId} onChange={(event) => setSelection({ evidenceId: evidence.id, symbolId: event.currentTarget.value })}>
          <option value="">{t("evidenceRange")}</option>
          {evidence.symbolIds.map((id) => {
            const symbol = evidence.symbols?.find((item) => item.id === id)
            const available = rangeForSymbol(symbol) !== null
            return <option key={id} value={id}>
              {symbol?.name ?? symbol?.label ?? id} — {symbolKind(symbol?.kind)}
              {symbol?.startLine ? ` · ${t("lines", { start: symbol.startLine, end: symbol.endLine ?? symbol.startLine })}` : ""}
              {!available ? ` · ${t("symbolRangeUnavailable")}` : ""}
            </option>
          })}
        </select>
      </label>
      {selectedSymbol && symbolRange && <span className="audit-evidence-symbol-location">
        <code>{selectedSymbol.source ?? evidence.source}</code> · {t("lines", { start: symbolRange.from, end: symbolRange.to })}
        {selectedSymbol.endLine !== null && selectedSymbol.endLine > lastLine && <span>{t("symbolPartialRange")}</span>}
      </span>}
      {selectedId && !symbolRange && !source.loading && <p role="status">{t("symbolNavigationUnavailable")}</p>}
    </div>}
    <p role="note">{t(source.file ? "auditedFileContent" : "historicalContent")}</p>
    {mismatch && <p role="status">{t(source.file ? "fileEvidenceMismatch" : "commitMismatch")}</p>}
    {source.file && !mismatch && rangesUnverified && <p role="status">{t("fileRangesUnverified")}</p>}
    {!verified && !source.file && !mismatch && !source.loading && <p role="status">{t("commitUnknown")}</p>}
    {source.failed && <div role="alert"><p>{t("auditedFileFailed")}</p><Button variant="secondary" onClick={source.retry}>{t("retry")}</Button></div>}
    {content !== null && location.unmapped && !symbolRange && <p role="note">{t("unmappedLines")}</p>}
    <div className="audit-evidence-code-frame" aria-busy={source.loading} data-loading={source.loading}>
      <div className="audit-evidence-code-layer" key={`${evidence.id}-${source.file ? "file" : "recorded"}`}>
        <CodeViewer code={content ?? ""} emptyText={t(verified ? "noContent" : "versionUnavailable")}
          language={language} highlight startLine={location.firstLine} scrollToLine={range?.from} scrollTargetKey={selectedId}
          marks={range ? [{ ...range, id: symbolRange ? selectedSymbol?.name ?? selectedSymbol?.id ?? t("symbol") : t("evidenceRange"), tone: "info" }] : []} />
      </div>
      {source.loading && <div className="audit-evidence-code-loading" role="status"><Spinner /><span>{t("loadingAuditedFile")}</span></div>}
    </div>
  </>
}

function WorkingCopyEvidenceCode({ evidence, projectId, repositoryName }: {
  evidence: AgentEvidence, projectId: number | null, repositoryName?: string
}) {
  const { t } = useTranslation("auditEvidence")
  const preview = useProjectFile(projectId)
  const path = evidenceFilePath(evidence.source, repositoryName)
  const file = preview.file !== null && preview.file.path === path ? preview.file : null
  const attempted = useRef<string | null>(null)
  const selectionKey = `${projectId}-${path}-${evidence.id}`
  const openFile = preview.open
  const loading = preview.loading
  const loadedPath = file?.path

  useEffect(() => {
    if (projectId === null || path === null || loadedPath === path || loading || attempted.current === selectionKey) return
    let active = true
    // Defer the hook's synchronous loading update; cleanup also prevents a
    // superseded selection (or StrictMode's first effect) from starting a read.
    queueMicrotask(() => {
      if (!active) return
      attempted.current = selectionKey
      openFile(path)
    })
    return () => { active = false }
  }, [projectId, path, loadedPath, loading, selectionKey, openFile])
  const content = file ? file.content : evidence.content
  const location = evidenceCodeLocation(file ? { ...evidence, kind: "file", content: file.content } : evidence)
  const extension = (file?.path ?? evidence.source)?.split(/[?#]/)[0].split(".").pop()?.toLowerCase() ?? ""
  const language = ({ tsx: "ts", mts: "ts", cts: "ts", jsx: "js", mjs: "js", cjs: "js" } as Record<string, string>)[extension] ?? extension

  return <>
    <div className="audit-evidence-file-actions">
      {projectId !== null && path !== null && <Button variant="secondary" disabled={preview.loading}
        onClick={() => preview.open(path)}>{t(preview.error ? "retryFile" : file ? "refreshFile" : "loadFile")}</Button>}
    </div>
    <p role="note">{t(file ? "currentFileNotice" : "storedContent")}</p>
    {projectId !== null && path === null && <p role="note">{t("filePathUnavailable")}</p>}
    {preview.error && <div role="alert"><p>{t("fileLoadFailed")}</p><p>{preview.error}</p></div>}
    {content !== null && location.unmapped && <p role="note">{t("unmappedLines")}</p>}
    <div className="audit-evidence-code-frame" aria-busy={preview.loading} data-loading={preview.loading}>
      <div className="audit-evidence-code-layer" key={`${evidence.id}-${file ? "file" : "recorded"}`}>
        <CodeViewer code={content ?? ""} emptyText={content === null ? t("noContent") : undefined}
          language={language} highlight startLine={location.firstLine} scrollToLine={location.range?.from}
          marks={location.range ? [{ ...location.range, id: t("evidenceRange"), tone: "info" }] : []} />
      </div>
      {preview.loading && <div className="audit-evidence-code-loading" role="status"><Spinner /><span>{t("loadingFile")}</span></div>}
    </div>
  </>
}

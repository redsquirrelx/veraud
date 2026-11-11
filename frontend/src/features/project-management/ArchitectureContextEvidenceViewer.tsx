import { useEffect } from "react"
import { useTranslation } from "react-i18next"
import { Button, ChevronLeftIcon, CodeViewer, Spinner } from "../../shared/ui-kit/index.ts"
import { evidenceFilePath } from "./auditAgentEvidence.ts"
import { useProjectFile } from "./useProjectFile.ts"
import type { ArchitectureContextCategorySource } from "./architectureContextView.ts"

interface ArchitectureContextEvidenceViewerProps {
  projectId: number | null
  repositoryName?: string
  evidence: ArchitectureContextCategorySource
  onBack: () => void
}

function viewerLanguage(path: string): string {
  const extension = path.split(/[?#]/)[0]!.split(".").pop()?.toLowerCase() ?? ""
  const languages: Record<string, string> = {
    tsx: "ts",
    mts: "ts",
    cts: "ts",
    jsx: "js",
    mjs: "js",
    cjs: "js",
  }
  return languages[extension] ?? extension
}

function rangeLabel(evidence: ArchitectureContextCategorySource): string {
  if (evidence.startLine === null) return ""
  return `L${evidence.startLine}–L${evidence.endLine ?? evidence.startLine}`
}

/** Detail view of an evidence explorer: a real project file around the cited range. */
export function ArchitectureContextEvidenceViewer({ projectId, repositoryName = "", evidence, onBack }: ArchitectureContextEvidenceViewerProps) {
  const { t } = useTranslation("projects")
  const preview = useProjectFile(projectId)
  const path = evidenceFilePath(evidence.filePath, repositoryName)
  const file = preview.file !== null && preview.file.path === path ? preview.file : null
  const openFile = preview.open

  useEffect(() => {
    if (path !== null) openFile(path)
  }, [openFile, path])

  const rangePresent = evidence.startLine !== null || evidence.endLine !== null
  const rangeValid = evidence.startLine !== null && evidence.endLine !== null
    && Number.isInteger(evidence.startLine) && Number.isInteger(evidence.endLine)
    && evidence.startLine > 0 && evidence.endLine >= evidence.startLine
  const lineCount = file === null || file.content === "" ? 0 : file.content.replace(/\n$/, "").split("\n").length
  const rangeWithinFile = rangeValid && evidence.startLine !== null && evidence.endLine !== null
    && evidence.startLine <= lineCount && evidence.endLine <= lineCount
  const range = rangeValid ? { from: evidence.startLine!, to: evidence.endLine! } : null
  const header = [path ?? evidence.filePath, rangeLabel(evidence)].filter((part) => part !== "").join(" · ")

  return (
    <div className="architecture-evidence-viewer">
      <div className="architecture-evidence-viewer-head">
        <Button variant="secondary" onClick={onBack}>
          <ChevronLeftIcon size={14} />{t("detail.overview.architectureContext.back")}
        </Button>
        <span className="mono architecture-evidence-viewer-title">{header}</span>
      </div>

      {evidence.quote !== "" && (
        <section className="architecture-evidence-excerpt-section" aria-label={t("detail.overview.architectureContext.referencedExcerpt")}>
          <span className="stage-section-label">{t("detail.overview.architectureContext.referencedExcerpt")}</span>
          <p>{evidence.quote}</p>
        </section>
      )}

      {path === null ? (
        <p className="files-error">{t("detail.overview.architectureContext.documentUnavailable")}</p>
      ) : rangePresent && !rangeValid ? (
        <p className="files-error">{t("detail.overview.architectureContext.invalidEvidenceRange")}</p>
      ) : preview.loading && file === null ? (
        <div className="files-loading" role="status" aria-label={t("detail.files.loading")}>
          <Spinner /><span className="label">{t("detail.files.loadingFile")}</span>
        </div>
      ) : preview.error !== "" ? (
        <div role="alert">
          <p className="files-error">{t("detail.overview.architectureContext.documentUnavailable")}</p>
          <p className="label">{preview.error}</p>
          <Button variant="secondary" onClick={() => preview.open(path)}>{t("detail.overview.architectureContext.retryEvidence")}</Button>
        </div>
      ) : file === null ? (
        <p className="files-error">{t("detail.overview.architectureContext.documentUnavailable")}</p>
      ) : rangeValid && !rangeWithinFile ? (
        <p className="files-error">{t("detail.overview.architectureContext.invalidEvidenceRange")}</p>
      ) : (
        <CodeViewer
          code={file.content}
          language={viewerLanguage(file.path)}
          highlight
          marks={range ? [{ id: t("detail.overview.architectureContext.evidenceRange"), from: range.from, to: range.to, tone: "warning", note: file.path }] : []}
          scrollToLine={range?.from}
          scrollTargetKey={`${file.path}:${range?.from ?? ""}-${range?.to ?? ""}`}
          initialWrapLines
        />
      )}
    </div>
  )
}

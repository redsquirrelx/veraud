import { useTranslation } from "react-i18next"
import { FilterTabs, ItemSearcher, ItemSelector } from "../../shared/ui-kit/index.ts"
import type { VersionAnalysisSummary } from "../../infrastructure/http-client/httpClient.ts"
import { analyzedLabel, derivedStatusLabelKey } from "./useAnalyzedVersions.ts"
import type { useVersionSelector } from "./useVersionSelector.ts"
import { AnalyzeMenu } from "./AnalyzeMenu.tsx"
import "./VersionSelector.css"

type Selection = ReturnType<typeof useVersionSelector>

export interface AnalysisAction {
  canAnalyze: boolean
  analyzing: boolean
  onAnalyze: (pipelineId: string) => void
}

export type VersionMode = "git" | "analyzed"

export interface AnalyzedSelection {
  versions: VersionAnalysisSummary[]
  loading: boolean
  error: string
  selectedId: number | null
  onSelect: (id: number) => void
  onRefresh: () => void
}

export function VersionLocation({ selection }: { selection: Selection }) {
  const { t } = useTranslation("projects")
  if (selection.detached !== null) {
    return <span className="label version-state">{t("version.detachedNotice", { hash: selection.detached })}</span>
  }
  return selection.applied === null ? null : <span className="label version-state">
    {t("version.appliedNotice", { branch: selection.applied.branch, shortHash: selection.applied.commitHash.slice(0, 7) })}
  </span>
}

export function VersionSelector({ selection, analysis, mode, onModeChange, analyzed, showLocation = true, size = "default" }: {
  selection: Selection
  analysis?: AnalysisAction
  mode?: VersionMode
  onModeChange?: (mode: VersionMode) => void
  analyzed?: AnalyzedSelection
  showLocation?: boolean
  size?: "default" | "compact"
}) {
  const { t } = useTranslation("projects")
  const current = mode ?? "git"
  const analyzeButton = analysis === undefined ? null : (
    <AnalyzeMenu canAnalyze={analysis.canAnalyze} analyzing={analysis.analyzing} onAnalyze={analysis.onAnalyze} />
  )
  const translateDerivedStatus = (status: string) => {
    const key = derivedStatusLabelKey(status)
    return key === null ? status : t(key)
  }

  return (
    <div className="version-selector">
      {analyzed !== undefined && (
        <FilterTabs
          label={t("version.sourceLabel")}
          options={[
            { id: "git", label: t("version.git"), count: 0 },
            { id: "analyzed", label: t("version.analyzed"), count: analyzed.versions.length },
          ]}
          value={current}
          onChange={(id) => onModeChange?.(id as VersionMode)}
        />
      )}
      {(selection.loadingBranches || selection.applying || selection.error !== "" || (showLocation && (selection.detached !== null || selection.applied !== null))) && <div className="version-row version-state-row">
      {selection.loadingBranches && <span className="label version-state">{t("version.loadingBranches")}</span>}
      {selection.applying && <span className="label version-state">{t("version.applying")}</span>}
      {selection.error !== "" && <span className="label version-state">{selection.error}</span>}

        {showLocation && <VersionLocation selection={selection} />}
      </div>}

      {current === "analyzed" && analyzed !== undefined ? (
        <div className="version-row">
          <ItemSelector
            items={analyzed.versions.map((version) => ({ id: String(version.id), label: analyzedLabel(version, translateDerivedStatus) }))}
            selectedId={analyzed.selectedId === null ? null : String(analyzed.selectedId)}
            onSelect={(id) => analyzed.onSelect(Number(id))}
            hasMore={false}
            onLoadMore={() => {}}
            emptyText={t("version.analyzedEmpty")}
            placeholder={t("version.analyzedPlaceholder")}
            label={t("version.analyzedLabel")}
            size={size}
            loading={analyzed.loading}
            onOpen={() => analyzed.onRefresh()}
          />
          {analyzeButton}
        </div>
      ) : (
      <div className="version-row">
        <ItemSelector
          items={selection.branches.map((name) => ({ id: name, label: name }))}
          selectedId={selection.detached === null && selection.branch !== "" ? selection.branch : null}
          onSelect={(name) => void selection.changeBranch(name)}
          hasMore={false}
          onLoadMore={() => {}}
          emptyText={t("version.branchesEmpty")}
          placeholder={selection.detached === null ? t("version.branchPlaceholder") : t("version.branchDetachedPlaceholder", { hash: selection.detached })}
          label={t("version.branchLabel")}
          size={size}
          loading={selection.loadingBranches}
          onOpen={() => void selection.refreshBranches()}
        />
        <ItemSearcher
          key={`${selection.branch}:${selection.commitHash}`}
          items={selection.commits.map((commit, index) => ({
            id: commit.commitHash,
            label: commit.commitHash.slice(0, 7),
            detail: index === 0 ? `(HEAD) ${commit.subject.slice(0, 60)}` : commit.subject.slice(0, 60),
          }))}
          selectedId={selection.commitHash === "" ? null : selection.commitHash}
          onSelect={(hash) => void selection.stageCommit(hash)}
          hasMore={false}
          onLoadMore={() => {}}
          emptyText={t("version.commitsEmpty")}
          placeholder=""
          label={t("version.commitLabel")}
          size={size}
          loading={selection.loadingCommits}
          disabled={selection.detached !== null || selection.applying}
        />
        {analyzeButton}
      </div>
      )}
      {current === "analyzed" && analyzed !== undefined && analyzed.error !== "" && (
        <span className="label version-error">{analyzed.error}</span>
      )}
    </div>
  )
}

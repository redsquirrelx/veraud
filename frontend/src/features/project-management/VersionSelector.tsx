import { FilterTabs, ItemSearcher, ItemSelector } from "../../shared/ui-kit/index.ts"
import type { VersionAnalysisSummary } from "../../infrastructure/http-client/httpClient.ts"
import { analyzedLabel } from "./useAnalyzedVersions.ts"
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
  if (selection.detached !== null) {
    return <span className="label version-state">(HEAD detached at {selection.detached}) - select a branch to re-attach</span>
  }
  return selection.applied === null ? null : <span className="label version-state">
    On {selection.applied.branch} at {selection.applied.commitHash.slice(0, 7)}
  </span>
}

export function VersionSelector({ selection, analysis, mode, onModeChange, analyzed, showLocation = true }: {
  selection: Selection
  analysis?: AnalysisAction
  mode?: VersionMode
  onModeChange?: (mode: VersionMode) => void
  analyzed?: AnalyzedSelection
  showLocation?: boolean
}) {
  const current = mode ?? "git"
  const analyzeButton = analysis === undefined ? null : (
    <AnalyzeMenu canAnalyze={analysis.canAnalyze} analyzing={analysis.analyzing} onAnalyze={analysis.onAnalyze} />
  )

  return (
    <div className="version-selector">
      {analyzed !== undefined && (
        <FilterTabs
          label="Version source"
          options={[
            { id: "git", label: "Git", count: 0 },
            { id: "analyzed", label: "Analyzed", count: analyzed.versions.length },
          ]}
          value={current}
          onChange={(id) => onModeChange?.(id as VersionMode)}
        />
      )}
      {(selection.loadingBranches || selection.applying || selection.error !== "" || (showLocation && (selection.detached !== null || selection.applied !== null))) && <div className="version-row version-state-row">
      {selection.loadingBranches && <span className="label version-state">Loading branches</span>}
      {selection.applying && <span className="label version-state">Applying version</span>}
      {selection.error !== "" && <span className="label version-state">{selection.error}</span>}

        {showLocation && <VersionLocation selection={selection} />}
      </div>}

      {current === "analyzed" && analyzed !== undefined ? (
        <div className="version-row">
          <ItemSelector
            items={analyzed.versions.map((version) => ({ id: String(version.id), label: analyzedLabel(version) }))}
            selectedId={analyzed.selectedId === null ? null : String(analyzed.selectedId)}
            onSelect={(id) => analyzed.onSelect(Number(id))}
            hasMore={false}
            onLoadMore={() => {}}
            emptyText="No analyzed versions yet"
            placeholder="Select an analyzed version"
            label="Analyzed version"
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
          emptyText="No branches found"
          placeholder={selection.detached === null ? "Select a branch" : `(HEAD detached at ${selection.detached})`}
          label="Branch"
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
          emptyText="No commits found"
          placeholder=""
          label="Commit"
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

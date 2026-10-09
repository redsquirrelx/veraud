import { Button, ItemSearcher, ItemSelector } from "../../shared/ui-kit/index.ts"
import type { useVersionSelector } from "./useVersionSelector.ts"
import "./VersionSelector.css"

type Selection = ReturnType<typeof useVersionSelector>

export interface AnalysisAction {
  canAnalyze: boolean
  analyzing: boolean
  onAnalyze: () => void
}

export function VersionSelector({ selection, analysis }: { selection: Selection; analysis?: AnalysisAction }) {
  return (
    <div className="version-selector">
      <div className="version-row version-state-row">
      {selection.loadingBranches && <span className="label version-state">Loading branches</span>}
      {selection.applying && <span className="label version-state">Applying version</span>}
      {selection.error !== "" && <span className="label version-state">{selection.error}</span>}

        {selection.detached !== null ? (
          <span className="label version-state">(HEAD detached at {selection.detached}) - select a branch to re-attach</span>
        ) : (
          selection.applied !== null && (
            <span className="label version-state">
              On {selection.applied.branch} at {selection.applied.commitHash.slice(0, 7)}
            </span>
          )
        )}
      </div>

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
        {analysis !== undefined && (
          <span className="version-analyze">
            <Button
              onClick={analysis.onAnalyze}
              disabled={!analysis.canAnalyze || analysis.analyzing}
              loading={analysis.analyzing}
              loadingText="Analyzing"
            >
              Analyze
            </Button>
          </span>
        )}
      </div>
    </div>
  )
}

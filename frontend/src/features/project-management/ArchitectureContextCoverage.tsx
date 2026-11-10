import { useLayoutEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys, TFunction } from "i18next"
import {
  ArrowRightIcon,
  Badge,
  CheckIcon,
  CodeIcon,
  DotsIcon,
  GridIcon,
  ListIcon,
  LockIcon,
  MinusIcon,
  Modal,
  ShieldIcon,
  SlidersIcon,
} from "../../shared/ui-kit/index.ts"
import { ArchitectureContextEvidenceList, type ArchitectureContextEvidenceGroup } from "./ArchitectureContextEvidenceList.tsx"
import { ArchitectureContextEvidenceViewer } from "./ArchitectureContextEvidenceViewer.tsx"
import { statusLabelKey } from "./projectStatus.ts"
import {
  ARCHITECTURE_CONTEXT_CATEGORIES,
  architectureContextCategoryDescriptionLabelKeys,
  architectureContextCategoryLabelKeys,
  getCategoryCoverageState,
  getCategorySources,
  getCoverageStats,
  groupCategorySources,
  type ArchitectureContextCategory,
  type ArchitectureContextCategoryCoverageState,
  type ArchitectureContextCategorySource,
  type ArchitectureContextCoverageState,
  type ArchitectureContextSummary,
} from "./architectureContextView.ts"
import "./PipelineStage.css"
import "./ArchitectureContextCoverage.css"

const categoryIconByCategory: Record<string, (props: { size?: number }) => React.ReactElement> = {
  architectural_style: SlidersIcon,
  components: GridIcon,
  responsibilities: ListIcon,
  relationships: ArrowRightIcon,
  constraints: LockIcon,
  interfaces_and_contracts: CodeIcon,
  architectural_decisions: ShieldIcon,
}

const coverageStatusIconByState: Record<ArchitectureContextCategoryCoverageState, (props: { size?: number }) => React.ReactElement> = {
  covered: CheckIcon,
  partial: DotsIcon,
  missing: MinusIcon,
}

function enumText(
  t: TFunction<"projects", undefined>,
  keys: Record<string, ParseKeys<"projects">>,
  value: string,
): string {
  const key = statusLabelKey(keys, value)
  return key === null ? value : t(key)
}

function overallTone(state: ArchitectureContextCoverageState): "success" | "warning" | "neutral" {
  if (state === "complete") return "success"
  if (state === "partial") return "warning"
  return "neutral"
}

function categoryTone(state: ArchitectureContextCategoryCoverageState): "success" | "warning" | "neutral" {
  if (state === "covered") return "success"
  if (state === "partial") return "warning"
  return "neutral"
}

type EvidenceExplorerView = "evidence-list" | "evidence-viewer"

/**
 * Documentary coverage only: "covered" means documented information was
 * recovered for the area; it is not an architecture compliance verdict.
 */
export function ArchitectureContextCoverage({ summary, projectId, repositoryName = "" }: { summary: ArchitectureContextSummary; projectId: number | null; repositoryName?: string }) {
  const { t } = useTranslation("projects")
  const [selectedCategory, setSelectedCategory] = useState<ArchitectureContextCategory | null>(null)
  const [viewState, setViewState] = useState<EvidenceExplorerView>("evidence-list")
  const [selectedEvidence, setSelectedEvidence] = useState<ArchitectureContextCategorySource | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())
  const modalBodyRef = useRef<HTMLDivElement | null>(null)
  const listScrollTop = useRef(0)
  const stats = getCoverageStats(summary)
  const overallLabelKey = stats.state === "complete"
    ? "detail.overview.architectureContext.coverageComplete"
    : stats.state === "partial"
      ? "detail.overview.architectureContext.coveragePartial"
      : "detail.overview.architectureContext.coverageMissing"
  const selectedSources = useMemo(() => selectedCategory === null ? [] : getCategorySources(summary, selectedCategory), [summary, selectedCategory])
  const selectedCoverageState = selectedCategory === null ? null : getCategoryCoverageState(summary, selectedCategory)
  const evidenceGroups = useMemo<ArchitectureContextEvidenceGroup[]>(() => groupCategorySources(selectedSources), [selectedSources])

  useLayoutEffect(() => {
    if (selectedCategory === null || viewState !== "evidence-list") return
    const element = modalBodyRef.current
    if (element === null) return
    if (typeof element.scrollTo === "function") element.scrollTo({ top: listScrollTop.current })
    else element.scrollTop = listScrollTop.current
  }, [selectedCategory, viewState])

  const openCategory = (category: ArchitectureContextCategory) => {
    setSelectedCategory(category)
    setSelectedEvidence(null)
    setViewState("evidence-list")
    setCollapsedGroups(new Set())
    listScrollTop.current = 0
  }

  const closeCoverageModal = () => {
    setSelectedCategory(null)
    setSelectedEvidence(null)
    setViewState("evidence-list")
    setCollapsedGroups(new Set())
    listScrollTop.current = 0
  }

  const toggleGroup = (filePath: string) => {
    setCollapsedGroups((current) => {
      const next = new Set(current)
      if (next.has(filePath)) next.delete(filePath)
      else next.add(filePath)
      return next
    })
  }

  const selectEvidence = (evidence: ArchitectureContextCategorySource) => {
    listScrollTop.current = modalBodyRef.current?.scrollTop ?? 0
    setSelectedEvidence(evidence)
    setViewState("evidence-viewer")
  }

  const backToEvidenceList = () => {
    setSelectedEvidence(null)
    setViewState("evidence-list")
  }

  return (
    <section className="architecture-coverage" aria-label={t("detail.overview.architectureContext.coverageTitle")}>
      <div className="architecture-coverage-overview">
        <span className="architecture-coverage-count">
          {t("detail.overview.architectureContext.areasCovered", { covered: stats.covered, total: stats.total })}
        </span>
        <Badge tone={overallTone(stats.state)}>{t(overallLabelKey)}</Badge>
        <div
          className="architecture-coverage-progress"
          role="progressbar"
          aria-label={t("detail.overview.architectureContext.coverageTitle")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={stats.percent}
        >
          <span className="architecture-coverage-progress-fill is-covered" style={{ width: `${stats.coveredPercent}%` }} />
          <span className="architecture-coverage-progress-fill is-partial" style={{ width: `${stats.partialPercent}%` }} />
        </div>
      </div>
      <p className="stage-footnote">{t("detail.overview.architectureContext.coverageNote")}</p>

      <div className="architecture-coverage-grid" role="group" aria-label={t("detail.overview.architectureContext.coverageTitle")}>
        {ARCHITECTURE_CONTEXT_CATEGORIES.map((category) => {
          const state = getCategoryCoverageState(summary, category)
          const Icon = categoryIconByCategory[category] ?? GridIcon
          const StatusIcon = coverageStatusIconByState[state]
          const selected = selectedCategory === category
          const statusLabel = state === "covered"
            ? t("detail.overview.architectureContext.coveredStatus")
            : state === "partial"
              ? t("detail.overview.architectureContext.partialStatus")
              : t("detail.overview.architectureContext.missingStatus")
          return (
            <button
              type="button"
              key={category}
              className="architecture-coverage-card"
              data-state={state}
              aria-pressed={selected}
              aria-expanded={selected}
              aria-haspopup="dialog"
              onClick={() => openCategory(category)}
            >
              <span className="architecture-coverage-card-top">
                <span className="architecture-coverage-icon"><Icon size={16} /></span>
                <span className="architecture-coverage-status-icon"><StatusIcon size={14} /></span>
              </span>
              <span className="architecture-coverage-title">{enumText(t, architectureContextCategoryLabelKeys, category)}</span>
              <span className="architecture-coverage-description">{enumText(t, architectureContextCategoryDescriptionLabelKeys, category)}</span>
              <span className="architecture-coverage-foot">
                <Badge tone={categoryTone(state)}>{statusLabel}</Badge>
              </span>
            </button>
          )
        })}
      </div>

      <div className="architecture-coverage-modal">
        <Modal
          open={selectedCategory !== null}
          label={selectedCategory === null ? "" : enumText(t, architectureContextCategoryLabelKeys, selectedCategory)}
          title={selectedCategory === null ? undefined : enumText(t, architectureContextCategoryLabelKeys, selectedCategory)}
          size="wide"
          onClose={closeCoverageModal}
        >
          {selectedCategory !== null && selectedCoverageState !== null && viewState === "evidence-list" && (
            <div className="architecture-coverage-modal-body" ref={modalBodyRef}>
              <div className="architecture-coverage-modal-meta">
                <Badge tone={categoryTone(selectedCoverageState)}>
                  {selectedCoverageState === "covered"
                    ? t("detail.overview.architectureContext.coveredStatus")
                    : selectedCoverageState === "partial"
                      ? t("detail.overview.architectureContext.partialStatus")
                      : t("detail.overview.architectureContext.missingStatus")}
                </Badge>
              </div>
              <p className="architecture-coverage-panel-description">{enumText(t, architectureContextCategoryDescriptionLabelKeys, selectedCategory)}</p>
              <ArchitectureContextEvidenceList
                groups={evidenceGroups}
                collapsedGroups={collapsedGroups}
                onToggleGroup={toggleGroup}
                onSelectEvidence={selectEvidence}
              />
            </div>
          )}
          {selectedCategory !== null && viewState === "evidence-viewer" && selectedEvidence !== null && (
            <ArchitectureContextEvidenceViewer
              projectId={projectId}
              repositoryName={repositoryName}
              evidence={selectedEvidence}
              onBack={backToEvidenceList}
            />
          )}
        </Modal>
      </div>
    </section>
  )
}

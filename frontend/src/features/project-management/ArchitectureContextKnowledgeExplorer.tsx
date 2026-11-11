import { useLayoutEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys, TFunction } from "i18next"
import { Badge, Button, Checkbox, ChevronLeftIcon, ChevronRightIcon, FilterTabs, ItemSelector, Modal } from "../../shared/ui-kit/index.ts"
import { statusLabelKey } from "./projectStatus.ts"
import {
  ARCHITECTURE_CONTEXT_CATEGORIES,
  architectureContextCategoryLabelKeys,
  architectureContextCertaintyLabelKeys,
  architectureContextConstraintLabelKeys,
  getClaimSources,
  groupCategorySources,
  type ArchitectureContextCategorySource,
  type ArchitectureContextClaimView,
  type ArchitectureContextSummary,
} from "./architectureContextView.ts"
import { ArchitectureContextEvidenceList, type ArchitectureContextEvidenceGroup } from "./ArchitectureContextEvidenceList.tsx"
import { ArchitectureContextEvidenceViewer } from "./ArchitectureContextEvidenceViewer.tsx"
import "./ArchitectureContextKnowledgeExplorer.css"

type KnowledgeExplorerView = "knowledge-list" | "knowledge-detail" | "evidence-viewer"

function enumText(
  t: TFunction<"projects", undefined>,
  keys: Record<string, ParseKeys<"projects">>,
  value: string,
): string {
  const key = statusLabelKey(keys, value)
  return key === null ? value : t(key)
}

function certaintyTone(value: string): "success" | "warning" | "info" {
  if (value === "explicit") return "success"
  if (value === "unknown") return "warning"
  return "info"
}

function constraintTone(value: string): "success" | "warning" | "info" | "neutral" {
  if (value === "required") return "info"
  if (value === "prohibited") return "warning"
  if (value === "allowed") return "success"
  return "neutral"
}

function scrollElementToTop(element: HTMLDivElement | null, top: number) {
  if (element === null) return
  if (typeof element.scrollTo === "function") element.scrollTo({ top })
  else element.scrollTop = top
}

/**
 * Master-detail explorer for extracted architectural knowledge. Coverage stays
 * a separate concern; this view only organizes claims and their evidence.
 */
export function ArchitectureContextKnowledgeExplorer({ summary, projectId, repositoryName = "" }: { summary: ArchitectureContextSummary; projectId: number | null; repositoryName?: string }) {
  const { t } = useTranslation("projects")
  const [categoryFilter, setCategoryFilter] = useState("all")
  const [certaintyFilter, setCertaintyFilter] = useState("all")
  const [requiredOnly, setRequiredOnly] = useState(false)
  const [viewState, setViewState] = useState<KnowledgeExplorerView>("knowledge-list")
  const [selectedKnowledge, setSelectedKnowledge] = useState<ArchitectureContextClaimView | null>(null)
  const [selectedEvidence, setSelectedEvidence] = useState<ArchitectureContextCategorySource | null>(null)
  const [collapsedEvidenceGroups, setCollapsedEvidenceGroups] = useState<Set<string>>(new Set())
  const modalBodyRef = useRef<HTMLDivElement | null>(null)
  const detailScrollTop = useRef(0)

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const claim of summary.knowledge) counts.set(claim.category, (counts.get(claim.category) ?? 0) + 1)
    return counts
  }, [summary.knowledge])

  const filteredKnowledge = useMemo(() => summary.knowledge.filter((claim) =>
    (categoryFilter === "all" || claim.category === categoryFilter)
    && (certaintyFilter === "all" || claim.certainty === certaintyFilter)
    && (!requiredOnly || claim.constraint === "required"),
  ), [summary.knowledge, categoryFilter, certaintyFilter, requiredOnly])

  const claimEvidenceGroups = useMemo<ArchitectureContextEvidenceGroup[]>(() =>
    selectedKnowledge === null ? [] : groupCategorySources(getClaimSources(selectedKnowledge)),
  [selectedKnowledge])

  useLayoutEffect(() => {
    if (viewState !== "knowledge-detail") return
    scrollElementToTop(modalBodyRef.current, detailScrollTop.current)
  }, [viewState])

  const selectKnowledge = (knowledge: ArchitectureContextClaimView) => {
    setSelectedKnowledge(knowledge)
    setSelectedEvidence(null)
    setCollapsedEvidenceGroups(new Set())
    detailScrollTop.current = 0
    setViewState("knowledge-detail")
  }

  const closeKnowledgeModal = () => {
    setSelectedKnowledge(null)
    setSelectedEvidence(null)
    setCollapsedEvidenceGroups(new Set())
    detailScrollTop.current = 0
    setViewState("knowledge-list")
  }

  const backToKnowledgeList = closeKnowledgeModal

  const selectEvidence = (evidence: ArchitectureContextCategorySource) => {
    detailScrollTop.current = modalBodyRef.current?.scrollTop ?? 0
    setSelectedEvidence(evidence)
    setViewState("evidence-viewer")
  }

  const backToKnowledgeDetail = () => {
    setSelectedEvidence(null)
    setViewState("knowledge-detail")
  }

  const toggleEvidenceGroup = (filePath: string) => {
    setCollapsedEvidenceGroups((current) => {
      const next = new Set(current)
      if (next.has(filePath)) next.delete(filePath)
      else next.add(filePath)
      return next
    })
  }

  const knowledgeModalOpen = selectedKnowledge !== null

  return (
    <section className="architecture-knowledge-explorer" aria-label={t("detail.overview.architectureContext.knowledge")}>
      <div className="architecture-knowledge-head">
        <span className="stage-section-label">{t("detail.overview.architectureContext.knowledge")}</span>
        <Badge tone="neutral">{filteredKnowledge.length}</Badge>
      </div>

      <div className="architecture-knowledge-filters">
        <FilterTabs
          label={t("detail.overview.architectureContext.categoryFilter")}
          value={categoryFilter}
          onChange={setCategoryFilter}
          options={[
            { id: "all", label: t("detail.overview.architectureContext.all"), count: summary.knowledge.length },
            ...ARCHITECTURE_CONTEXT_CATEGORIES.map((category) => ({
              id: category,
              label: enumText(t, architectureContextCategoryLabelKeys, category),
              count: categoryCounts.get(category) ?? 0,
            })),
          ]}
        />
        <ItemSelector
          label={t("detail.overview.architectureContext.explicitnessFilter")}
          items={[
            { id: "all", label: t("detail.overview.architectureContext.all") },
            { id: "explicit", label: t("detail.overview.architectureContext.certainty.explicit") },
            { id: "derived", label: t("detail.overview.architectureContext.certainty.derived") },
            { id: "unknown", label: t("detail.overview.architectureContext.certainty.unknown") },
          ]}
          selectedId={certaintyFilter}
          onSelect={setCertaintyFilter}
          hasMore={false}
          onLoadMore={() => {}}
          emptyText={t("detail.overview.architectureContext.noKnowledgeItems")}
          size="compact"
        />
        <Checkbox
          label={t("detail.overview.architectureContext.requiredOnly")}
          checked={requiredOnly}
          onChange={setRequiredOnly}
        />
      </div>

      {filteredKnowledge.length === 0 ? (
        <p className="label">{t("detail.overview.architectureContext.noKnowledgeItems")}</p>
      ) : (
        <div className="architecture-knowledge-grid">
          {filteredKnowledge.map((knowledge, index) => (
            <button
              type="button"
              key={`${knowledge.category}-${knowledge.subject}-${index}`}
              className="architecture-knowledge-card"
              aria-haspopup="dialog"
              onClick={() => selectKnowledge(knowledge)}
            >
              <span className="architecture-knowledge-card-top">
                <span className="architecture-knowledge-category">{enumText(t, architectureContextCategoryLabelKeys, knowledge.category)}</span>
                <span className="architecture-knowledge-chevron"><ChevronRightIcon size={14} /></span>
              </span>
              <span className="architecture-knowledge-title">{knowledge.subject}</span>
              <span className="architecture-knowledge-description">{knowledge.statement}</span>
              <span className="architecture-knowledge-foot">
                {knowledge.certainty !== "" && (
                  <Badge tone={certaintyTone(knowledge.certainty)}>
                    {enumText(t, architectureContextCertaintyLabelKeys, knowledge.certainty)}
                  </Badge>
                )}
                {knowledge.constraint !== "" && knowledge.constraint !== "unspecified" && (
                  <Badge tone={constraintTone(knowledge.constraint)}>
                    {enumText(t, architectureContextConstraintLabelKeys, knowledge.constraint)}
                  </Badge>
                )}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="architecture-knowledge-modal">
        <Modal
          open={knowledgeModalOpen}
          label={selectedKnowledge === null ? "" : selectedKnowledge.subject}
          title={selectedKnowledge === null ? undefined : selectedKnowledge.subject}
          size="wide"
          onClose={closeKnowledgeModal}
        >
          {selectedKnowledge !== null && viewState === "knowledge-detail" && (
            <div className="architecture-knowledge-modal-body" ref={modalBodyRef}>
              <div className="architecture-knowledge-detail-head">
                <Button variant="secondary" onClick={backToKnowledgeList}>
                  <ChevronLeftIcon size={14} />{t("detail.overview.architectureContext.back")}
                </Button>
              </div>
              <div className="architecture-knowledge-detail">
                <p className="stage-lede">{selectedKnowledge.statement}</p>
                <div className="architecture-knowledge-meta">
                  <Badge tone="neutral">{enumText(t, architectureContextCategoryLabelKeys, selectedKnowledge.category)}</Badge>
                  {selectedKnowledge.certainty !== "" && (
                    <Badge tone={certaintyTone(selectedKnowledge.certainty)}>
                      {enumText(t, architectureContextCertaintyLabelKeys, selectedKnowledge.certainty)}
                    </Badge>
                  )}
                  {selectedKnowledge.constraint !== "" && selectedKnowledge.constraint !== "unspecified" && (
                    <Badge tone={constraintTone(selectedKnowledge.constraint)}>
                      {enumText(t, architectureContextConstraintLabelKeys, selectedKnowledge.constraint)}
                    </Badge>
                  )}
                </div>
                <span className="stage-section-label">{t("detail.overview.architectureContext.rationale")}</span>
                <p className="architecture-knowledge-reasoning">{selectedKnowledge.reasoning}</p>
                {selectedKnowledge.relatedSubjects.length > 0 && <p className="stage-row-sub">→ {selectedKnowledge.relatedSubjects.join(", ")}</p>}
                <span className="stage-section-label">{t("detail.overview.architectureContext.evidence")}</span>
                <ArchitectureContextEvidenceList
                  groups={claimEvidenceGroups}
                  collapsedGroups={collapsedEvidenceGroups}
                  onToggleGroup={toggleEvidenceGroup}
                  onSelectEvidence={selectEvidence}
                />
              </div>
            </div>
          )}
          {selectedKnowledge !== null && viewState === "evidence-viewer" && selectedEvidence !== null && (
            <ArchitectureContextEvidenceViewer
              projectId={projectId}
              repositoryName={repositoryName}
              evidence={selectedEvidence}
              onBack={backToKnowledgeDetail}
            />
          )}
        </Modal>
      </div>
    </section>
  )
}

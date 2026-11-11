import { useTranslation } from "react-i18next"
import { ChevronDownIcon, ChevronRightIcon, CodeIcon, FolderIcon } from "../../shared/ui-kit/index.ts"
import type { ArchitectureContextCategorySource } from "./architectureContextView.ts"

export interface ArchitectureContextEvidenceGroup {
  filePath: string
  references: ArchitectureContextCategorySource[]
}

interface ArchitectureContextEvidenceListProps {
  groups: ArchitectureContextEvidenceGroup[]
  collapsedGroups: Set<string>
  onToggleGroup: (filePath: string) => void
  onSelectEvidence: (evidence: ArchitectureContextCategorySource) => void
}

function fileName(filePath: string): string {
  const parts = filePath.split("/").filter((part) => part !== "")
  return parts.at(-1) ?? filePath
}

function rangeLabel(evidence: ArchitectureContextCategorySource): string {
  if (evidence.startLine === null) return ""
  return `L${evidence.startLine}–L${evidence.endLine ?? evidence.startLine}`
}

/** Master view of an evidence explorer: document groups own their references. */
export function ArchitectureContextEvidenceList({ groups, collapsedGroups, onToggleGroup, onSelectEvidence }: ArchitectureContextEvidenceListProps) {
  const { t } = useTranslation("projects")

  if (groups.length === 0) {
    return <p className="label">{t("detail.overview.architectureContext.noCategoryEvidence")}</p>
  }

  return (
    <div className="architecture-evidence-list">
      {groups.map((group) => {
        const expanded = !collapsedGroups.has(group.filePath)
        return (
          <section className="architecture-evidence-group" key={group.filePath}>
            <button
              type="button"
              className="architecture-evidence-group-head"
              aria-expanded={expanded}
              aria-label={t(expanded ? "detail.overview.architectureContext.collapseDocument" : "detail.overview.architectureContext.expandDocument", { document: fileName(group.filePath) })}
              onClick={() => onToggleGroup(group.filePath)}
            >
              <span className="architecture-evidence-group-icon"><FolderIcon size={16} /></span>
              <span className="architecture-evidence-group-main">
                <span className="architecture-evidence-document">{fileName(group.filePath)}</span>
                <span className="architecture-evidence-path">{group.filePath}</span>
              </span>
              <span className="architecture-evidence-chevron">{expanded ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}</span>
            </button>
            {expanded && (
              <div className="architecture-evidence-references">
                {group.references.map((evidence, index) => {
                  const range = rangeLabel(evidence)
                  return (
                    <button
                      type="button"
                      key={`${evidence.filePath}-${evidence.startLine ?? ""}-${evidence.endLine ?? ""}-${index}`}
                      className="architecture-evidence-row"
                      aria-label={range === "" ? evidence.filePath : `${evidence.filePath} ${range}`}
                      onClick={() => onSelectEvidence(evidence)}
                    >
                      <span className="architecture-evidence-row-icon"><CodeIcon size={14} /></span>
                      <span className="architecture-evidence-row-main">
                        <span className="architecture-evidence-row-head">
                          <span className="mono architecture-evidence-file">{evidence.filePath}</span>
                          {range !== "" && <span className="architecture-evidence-range">{range}</span>}
                        </span>
                        {evidence.quote !== "" && <span className="architecture-evidence-excerpt">{evidence.quote}</span>}
                      </span>
                      <span className="architecture-evidence-chevron"><ChevronRightIcon size={14} /></span>
                    </button>
                  )
                })}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}

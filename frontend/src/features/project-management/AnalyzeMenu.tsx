import { DropdownMenu } from "../../shared/ui-kit/index.ts"
import { PIPELINES } from "./pipelines.ts"
import "./VersionSelector.css"

export interface AnalyzeMenuProps {
  canAnalyze: boolean
  analyzing: boolean
  onAnalyze: (pipelineId: string) => void
  onAudit?: () => void
}

/** Pipeline picker: the same menu wherever an analysis can start. */
export function AnalyzeMenu({ canAnalyze, analyzing, onAnalyze, onAudit }: AnalyzeMenuProps) {
  return (
    <span className="version-analyze">
      <DropdownMenu
        label="Analyze"
        items={[
          ...PIPELINES.map((option) => ({ id: option.id, label: option.label, description: option.description })),
          ...(onAudit ? [{ id: "quality-audit", label: "Mantenibilidad", description: "Auditoría de calidad e informe Word" }] : []),
        ]}
        onSelect={(id) => id === "quality-audit" && onAudit ? onAudit() : onAnalyze(id)}
        disabled={!canAnalyze || analyzing}
        loading={analyzing}
        loadingText="Analyzing"
        align="end"
      />
    </span>
  )
}

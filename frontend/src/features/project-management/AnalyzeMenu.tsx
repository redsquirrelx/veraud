import { DropdownMenu } from "../../shared/ui-kit/index.ts"
import { PIPELINES } from "./pipelines.ts"
import "./VersionSelector.css"

export interface AnalyzeMenuProps {
  canAnalyze: boolean
  analyzing: boolean
  onAnalyze: (pipelineId: string) => void
}

/** Pipeline picker: the same menu wherever an analysis can start. */
export function AnalyzeMenu({ canAnalyze, analyzing, onAnalyze }: AnalyzeMenuProps) {
  return (
    <span className="version-analyze">
      <DropdownMenu
        label="Analyze"
        items={PIPELINES.map((option) => ({ id: option.id, label: option.label, description: option.description }))}
        onSelect={onAnalyze}
        disabled={!canAnalyze || analyzing}
        loading={analyzing}
        loadingText="Analyzing"
        align="end"
      />
    </span>
  )
}

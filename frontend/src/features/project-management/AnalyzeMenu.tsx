import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { DropdownMenu } from "../../shared/ui-kit/index.ts"
import { PIPELINES } from "./pipelines.ts"
import "./VersionSelector.css"

export interface AnalyzeMenuProps {
  canAnalyze: boolean
  analyzing: boolean
  onAnalyze: (pipelineId: string) => void
  onAudit?: () => void
}

const pipelineTextKeys: Record<string, { labelKey: ParseKeys<"projects">, descriptionKey: ParseKeys<"projects"> }> = {
  "project-architecture": {
    labelKey: "analyze.pipelines.projectArchitecture.label",
    descriptionKey: "analyze.pipelines.projectArchitecture.description",
  },
}

/** Pipeline picker: the same menu wherever an analysis can start. */
export function AnalyzeMenu({ canAnalyze, analyzing, onAnalyze, onAudit }: AnalyzeMenuProps) {
  const { t } = useTranslation("projects")
  return (
    <span className="version-analyze">
      <DropdownMenu
        label={t("analyze.label")}
        items={[...PIPELINES.map((option) => {
          const keys = pipelineTextKeys[option.id]
          return {
            id: option.id,
            label: keys === undefined ? option.label : t(keys.labelKey),
            description: keys === undefined ? option.description : t(keys.descriptionKey),
          }
        }), ...(onAudit ? [{ id: "quality-audit", label: t("analyze.audit.label"), description: t("analyze.audit.description") }] : [])]}
        onSelect={(id) => id === "quality-audit" && onAudit ? onAudit() : onAnalyze(id)}
        disabled={!canAnalyze || analyzing}
        loading={analyzing}
        loadingText={t("analyze.loading")}
        align="end"
      />
    </span>
  )
}

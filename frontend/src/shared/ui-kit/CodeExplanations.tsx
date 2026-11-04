import { useTranslation } from "react-i18next"
import type { CodeExplanation } from "./codeViewer.ts"
import "./CodeExplanations.css"
import "./CodeReference.css"

export function CodeExplanations({ items }: { items: CodeExplanation[] }) {
  const { t } = useTranslation("common")
  if (items.length === 0) {
    return null
  }

  return (
    <ul className="ui-code-explanations" aria-label={t("ui.codeExplanations.label")}>
      {items.map((item) => (
        <li key={item.id} className={`ui-code-explanation ui-code-explanation-${item.tone}`}>
          <span className={`ui-code-ref ui-code-ref-${item.tone}`}>{item.id}</span>
          <div className="ui-code-explanation-body">
            <span className="mono">{item.title}</span>
            <p>{item.body}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}

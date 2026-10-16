import { useTranslation } from "react-i18next"
import { Badge, Button, MinusIcon, PencilIcon } from "../../shared/ui-kit/index.ts"
import "./ModelListItem.css"

interface ModelListItemProps {
  name: string
  provider: string
  inUse: boolean
  onEdit: () => void
  onRemove: () => void
}

export function ModelListItem({ name, provider, inUse, onEdit, onRemove }: ModelListItemProps) {
  const { t } = useTranslation("settings")
  return (
    <span className="settings-model-item">
      <span className="settings-model-main">
        <span className="mono">{name}</span>
        <span className="label">{provider}</span>
      </span>
      <span className="settings-model-side">
        {inUse && <Badge tone="neutral">{t("models.inUse")}</Badge>}
        <span onClick={(event) => event.stopPropagation()}>
          <Button variant="secondary" square ariaLabel={t("models.editItem", { name })} title={t("models.editItem", { name })} onClick={onEdit}>
            <PencilIcon />
          </Button>
        </span>
        <span onClick={(event) => event.stopPropagation()}>
          <Button variant="secondary" square ariaLabel={t("models.removeItem", { name })} title={t("models.removeItem", { name })} disabled={inUse} onClick={onRemove}>
            <MinusIcon />
          </Button>
        </span>
      </span>
    </span>
  )
}

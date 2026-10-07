import { Badge, Button, MinusIcon } from "../../shared/ui-kit/index.ts"
import "./ModelListItem.css"

interface ModelListItemProps {
  name: string
  provider: string
  inUse: boolean
  onRemove: () => void
}

export function ModelListItem({ name, provider, inUse, onRemove }: ModelListItemProps) {
  return (
    <span className="settings-model-item">
      <span className="settings-model-main">
        <span className="mono">{name}</span>
        <span className="label">{provider}</span>
      </span>
      <span className="settings-model-side">
        {inUse && <Badge tone="neutral">In use</Badge>}
        <span onClick={(event) => event.stopPropagation()}>
          <Button variant="secondary" square ariaLabel={`Remove ${name}`} title={`Remove ${name}`} disabled={inUse} onClick={onRemove}>
            <MinusIcon />
          </Button>
        </span>
      </span>
    </span>
  )
}

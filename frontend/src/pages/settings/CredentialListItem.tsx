import { Badge, Button, MinusIcon, PencilIcon } from "../../shared/ui-kit/index.ts"
import "./CredentialListItem.css"

interface CredentialListItemProps {
  name: string
  provider: string
  apiKeyPreview: string
  inUse: boolean
  onEdit: () => void
  onRemove: () => void
}

export function CredentialListItem({ name, provider, apiKeyPreview, inUse, onEdit, onRemove }: CredentialListItemProps) {
  return (
    <span className="settings-credential-item">
      <span className="settings-credential-main">
        <span className="settings-credential-title">
          <span className="mono">{name}</span>
        </span>
        <span className="label">{provider}</span>
      </span>
      <span className="label settings-credential-caption">API key</span>
      <span className="mono settings-credential-preview">{apiKeyPreview}</span>
      <span className="settings-credential-side">
        {inUse && <Badge tone="neutral">In use</Badge>}
        <span onClick={(event) => event.stopPropagation()}>
          <Button variant="secondary" square ariaLabel={`Edit ${name}`} title={`Edit ${name}`} onClick={onEdit}>
            <PencilIcon />
          </Button>
        </span>
        <span onClick={(event) => event.stopPropagation()}>
          <Button variant="secondary" square ariaLabel={`Remove ${name}`} title={`Remove ${name}`} disabled={inUse} onClick={onRemove}>
            <MinusIcon />
          </Button>
        </span>
      </span>
    </span>
  )
}

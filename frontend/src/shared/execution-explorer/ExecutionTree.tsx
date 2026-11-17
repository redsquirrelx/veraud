import { useId } from "react"
import { useTranslation } from "react-i18next"
import { Badge, ChevronDownIcon } from "../ui-kit/index.ts"
import { useAuditStateLabel } from "../audit-monitor/monitorLabels.ts"
import { displayAgentName } from "./explorerPresentation.ts"
import { stateTone, type AuditAgentNode } from "../audit-monitor/auditStatus.ts"

interface ExecutionTreeProps {
  nodes: AuditAgentNode[]
  selectedAgentId: string | null
  /** Agents whose children are hidden; everything starts expanded. */
  collapsed: ReadonlySet<string>
  onToggle: (agentId: string) => void
  onSelect: (agentId: string) => void
}

/** Expandable audit agent tree (manager → coordinator → investigators). Kept
 *  separate because standalone agents never render a tree at all. */
export function ExecutionTree({ nodes, selectedAgentId, collapsed, onToggle, onSelect }: ExecutionTreeProps) {
  return (
    <ul className="execution-explorer-tree">
      {nodes.map((node) => (
        <ExecutionTreeNode key={node.agent.id} node={node} selectedAgentId={selectedAgentId} collapsed={collapsed} onToggle={onToggle} onSelect={onSelect} />
      ))}
    </ul>
  )
}

function ExecutionTreeNode({ node, selectedAgentId, collapsed, onToggle, onSelect }: {
  node: AuditAgentNode
  selectedAgentId: string | null
  collapsed: ReadonlySet<string>
  onToggle: (agentId: string) => void
  onSelect: (agentId: string) => void
}) {
  const { t } = useTranslation("executionExplorer")
  const stateLabel = useAuditStateLabel()
  const groupId = useId()
  const agent = node.agent
  const nodeId = String(agent.id)
  const hasChildren = node.children.length > 0
  const isCollapsed = collapsed.has(nodeId)
  const selected = nodeId === selectedAgentId
  const phase = agent.state === "running" && agent.phase ? agent.phase.replaceAll("_", " ") : null
  const name = displayAgentName(agent, t)

  return (
    <li className="execution-explorer-node" data-state={agent.state}>
      <div className="execution-explorer-node-row">
        {hasChildren ? (
          <button
            type="button"
            className="execution-explorer-node-toggle"
            aria-expanded={!isCollapsed}
            aria-controls={groupId}
            aria-label={t("node.toggle", { name })}
            onClick={() => onToggle(nodeId)}
          >
            <span className="execution-explorer-node-chevron" data-expanded={!isCollapsed} aria-hidden="true"><ChevronDownIcon size={12} /></span>
          </button>
        ) : (
          <span className="execution-explorer-node-spacer" aria-hidden="true" />
        )}
        <button
          type="button"
          className="execution-explorer-node-select"
          data-selected={selected}
          aria-pressed={selected}
          title={name}
          onClick={() => onSelect(nodeId)}
        >
          <span className="execution-explorer-node-status" data-status={agent.state} aria-hidden="true" />
          <span className="execution-explorer-node-name">{name}</span>
          {phase && <span className="execution-explorer-node-phase">{phase}</span>}
          <Badge tone={stateTone(agent.state)} compact>{stateLabel(agent.state)}</Badge>
        </button>
      </div>
      {hasChildren && (
        <div id={groupId} hidden={isCollapsed}>
          {!isCollapsed && <ExecutionTree nodes={node.children} selectedAgentId={selectedAgentId} collapsed={collapsed} onToggle={onToggle} onSelect={onSelect} />}
        </div>
      )}
    </li>
  )
}

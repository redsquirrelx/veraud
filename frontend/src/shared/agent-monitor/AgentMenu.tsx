import { useState } from "react"
import { Card, CheckIcon, ChevronDownIcon, ChevronUpIcon, CrossIcon, Spinner, XIcon } from "../ui-kit/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import "./AgentMenu.css"

export function AgentMenu({ executions }: { executions: AgentExecution[] }) {
  const [expanded, setExpanded] = useState(false)
  const [open, setOpen] = useState(false)
  const [closing, setClosing] = useState(false)
  const [prevCount, setPrevCount] = useState(0)

  if (executions.length !== prevCount) {
    setPrevCount(executions.length)
    if (executions.length > 0) {
      setOpen(true)
      setClosing(false)
    }
  }

  if (!open) {
    return null
  }

  const current = executions.find((execution) => execution.status === "Running")
    ?? executions.find((execution) => execution.status === "Waiting")
    ?? executions[executions.length - 1]
  const shown = expanded ? [...executions].reverse() : current === undefined ? [] : [current]

  function close() {
    if (closing) {
      return
    }
    setClosing(true)
    setTimeout(() => {
      setOpen(false)
      setClosing(false)
    }, 200)
  }

  return (
    <div className={closing ? "agent-menu agent-menu-closing" : "agent-menu"} role="status" aria-label="Agent runs">
      <div className="agent-menu-top">
        <button
          type="button"
          className="agent-menu-header"
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse agents" : "Expand agents"}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="label">Agent runs ({executions.length})</span>
          {expanded ? <ChevronDownIcon /> : <ChevronUpIcon />}
        </button>
        <button
          type="button"
          className="agent-menu-close"
          aria-label="Close agent menu"
          onClick={() => close()}
        >
          <XIcon size={13} />
        </button>
      </div>
      {expanded && executions.length === 0 ? (
        <span className="label">No agent runs</span>
      ) : (
        <div className="agent-menu-list" key={expanded ? "open" : "shut"}>
          {shown.map((execution) => (
            <Card key={execution.id}>
              <div className="agent-row">
                {execution.status === "Completed" ? (
                  <span className="agent-icon-done" role="img" aria-label="Done">
                    <CheckIcon size={14} />
                  </span>
                ) : execution.status === "Failed" ? (
                  <span className="agent-icon-failed" role="img" aria-label="Failed">
                    <CrossIcon size={14} />
                  </span>
                ) : (
                  <Spinner size={12} />
                )}
                <span className="mono">{execution.agentType} run #{execution.id}</span>
                <span className="label">{execution.status}</span>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

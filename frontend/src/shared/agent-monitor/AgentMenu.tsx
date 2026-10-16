import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { Card, CheckIcon, ChevronDownIcon, ChevronUpIcon, CrossIcon, Spinner, XIcon } from "../ui-kit/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import "./AgentMenu.css"
import { AgentTokenUsage } from "./AgentTokenUsage.tsx"

const EXECUTION_STATUS_LABEL_KEYS: Record<string, ParseKeys<"agents">> = {
  Running: "execution.status.running",
  Waiting: "execution.status.waiting",
  Completed: "execution.status.completed",
  Failed: "execution.status.failed",
}

export function AgentMenu({ executions }: { executions: AgentExecution[] }) {
  const { t } = useTranslation("agents")
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
    <div className={closing ? "agent-menu agent-menu-closing" : "agent-menu"} role="status" aria-label={t("menu.label")}>
      <div className="agent-menu-top">
        <button
          type="button"
          className="agent-menu-header"
          aria-expanded={expanded}
          aria-label={t(expanded ? "menu.collapse" : "menu.expand")}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="label">{t("menu.title", { count: executions.length })}</span>
          {expanded ? <ChevronDownIcon /> : <ChevronUpIcon />}
        </button>
        <button
          type="button"
          className="agent-menu-close"
          aria-label={t("menu.close")}
          onClick={() => close()}
        >
          <XIcon size={13} />
        </button>
      </div>
      {expanded && executions.length === 0 ? (
        <span className="label">{t("menu.empty")}</span>
      ) : (
        <div className="agent-menu-list" key={expanded ? "open" : "shut"}>
          {shown.map((execution) => (
            <Card key={execution.id}>
              <div className="agent-row">
                {execution.status === "Completed" ? (
                  <span className="agent-icon-done" role="img" aria-label={t("menu.done")}>
                    <CheckIcon size={14} />
                  </span>
                ) : execution.status === "Failed" ? (
                  <span className="agent-icon-failed" role="img" aria-label={t("menu.failed")}>
                    <CrossIcon size={14} />
                  </span>
                ) : (
                  <Spinner size={12} />
                )}
                <span className="mono">{t("menu.runTitle", { agentType: execution.agentType, id: execution.id })}</span>
                <span className="label">{EXECUTION_STATUS_LABEL_KEYS[execution.status] !== undefined ? t(EXECUTION_STATUS_LABEL_KEYS[execution.status]!) : execution.status}</span>
              </div>
              <AgentTokenUsage execution={execution} />
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

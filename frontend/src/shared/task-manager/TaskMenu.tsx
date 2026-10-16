import { useId, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { Card, CheckIcon, ChevronDownIcon, ChevronUpIcon, CrossIcon, Spinner, XIcon } from "../../shared/ui-kit/index.ts"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"
import "./TaskMenu.css"

const TASK_STATUS_LABEL_KEYS: Record<string, ParseKeys<"tasks">> = {
  Running: "status.running",
  Queued: "status.queued",
  Succeded: "status.succeeded",
  Failed: "status.failed",
}

export function TaskMenu({ tasks }: { tasks: ActiveTask[] }) {
  const { t } = useTranslation("tasks")
  const id = useId()
  const [expandedTasks, setExpandedTasks] = useState<Set<number>>(() => new Set())
  const [expanded, setExpanded] = useState(false)
  const [open, setOpen] = useState(false)
  const [closing, setClosing] = useState(false)
  const [prevCount, setPrevCount] = useState(0)

  if (tasks.length !== prevCount) {
    setPrevCount(tasks.length)
    if (tasks.length > 0) {
      setOpen(true)
      setClosing(false)
    }
  }

  if (!open) {
    return null
  }

  const current = tasks.find((task) => task.status === "Running") ?? tasks[tasks.length - 1]
  const shown = expanded ? [...tasks].reverse() : current === undefined ? [] : [current]

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
    <div className={closing ? "task-menu task-menu-closing" : "task-menu"} role="status" aria-label={t("menu.label")}>
      <div className="task-menu-top">
        <button
          type="button"
          className="task-menu-header"
          aria-expanded={expanded}
          aria-label={t(expanded ? "menu.collapse" : "menu.expand")}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="label">{t("menu.title", { count: tasks.length })}</span>
          {expanded ? <ChevronDownIcon /> : <ChevronUpIcon />}
        </button>
        <button
          type="button"
          className="task-menu-close"
          aria-label={t("menu.close")}
          onClick={() => close()}
        >
          <XIcon size={13} />
        </button>
      </div>
      {expanded && tasks.length === 0 ? (
        <span className="label">{t("menu.empty")}</span>
      ) : (
        <div className="task-menu-list" key={expanded ? "open" : "shut"}>
          {shown.map((task) => (
            <Card key={task.id}>
              <button
                type="button"
                className="task-row task-row-toggle"
                aria-expanded={expandedTasks.has(task.id)}
                aria-controls={`${id}-command-${task.id}`}
                aria-label={t(expandedTasks.has(task.id) ? "menu.hideCommandFor" : "menu.showCommandFor", { name: task.description ?? `${task.repositoryOwner}/${task.repositoryName}` })}
                onClick={() => setExpandedTasks((current) => {
                  const next = new Set(current)
                  if (next.has(task.id)) next.delete(task.id)
                  else next.add(task.id)
                  return next
                })}
              >
                {task.status === "Succeded" ? (
                  <span className="task-icon-done" role="img" aria-label={t("menu.done")}>
                    <CheckIcon size={14} />
                  </span>
                ) : task.status === "Failed" ? (
                  <span className="task-icon-failed" role="img" aria-label={t("menu.failed")}>
                    <CrossIcon size={14} />
                  </span>
                ) : (
                  <Spinner size={12} />
                )}
                <span className="mono">{task.description ?? `${task.repositoryOwner}/${task.repositoryName}`}</span>
                <span className="label">{TASK_STATUS_LABEL_KEYS[task.status] !== undefined ? t(TASK_STATUS_LABEL_KEYS[task.status]!) : task.status}</span>
                <span className="task-command-chevron" data-expanded={expandedTasks.has(task.id)} aria-hidden="true"><ChevronDownIcon size={12} /></span>
              </button>
              <div id={`${id}-command-${task.id}`} className="task-command-detail" data-expanded={expandedTasks.has(task.id)} aria-hidden={!expandedTasks.has(task.id)} inert={!expandedTasks.has(task.id)}>
                <div className="task-command-inner">
                  <div className="task-command-content">
                    <span className="label">{t("menu.command")}</span>
                    {task.command ? <pre className="task-command"><code>{task.command}</code></pre> : <span className="task-command-unavailable">{t("menu.commandUnavailable")}</span>}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

import { isTaskVisible, TaskMenu, useTaskVisibility, useTasks } from "../shared/task-manager/index.ts"
import { AgentMenu, useAgentExecutions } from "../shared/agent-monitor/index.ts"
import { Toast } from "../shared/ui-kit/index.ts"
import { useToasts } from "./use-toasts.ts"

export function Dock() {
  const tasks = useTasks()
  const [visibility] = useTaskVisibility()
  const executions = useAgentExecutions()
  const { toasts, dismissToast } = useToasts()
  const visibleTasks = tasks.filter((task) => isTaskVisible(task, visibility))

  return (
    <div className="dock">
      {toasts.map((toast) => (
        <Toast key={toast.id} kind={toast.kind} message={toast.message} onClose={() => dismissToast(toast.id)} />
      ))}
      <TaskMenu tasks={visibleTasks} />
      <AgentMenu executions={executions} />
    </div>
  )
}

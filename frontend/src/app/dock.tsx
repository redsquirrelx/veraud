import { TaskMenu } from "../features/project-management/TaskMenu.tsx"
import { useTasks } from "../features/project-management/useTasks.ts"
import { Toast } from "../shared/ui-kit/index.ts"
import { useToasts } from "./use-toasts.ts"

export function Dock() {
  const tasks = useTasks()
  const { toasts, dismissToast } = useToasts()

  return (
    <div className="dock">
      {toasts.map((toast) => (
        <Toast key={toast.id} kind={toast.kind} message={toast.message} onClose={() => dismissToast(toast.id)} />
      ))}
      <TaskMenu tasks={tasks} />
    </div>
  )
}

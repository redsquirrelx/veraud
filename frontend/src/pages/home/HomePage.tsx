import { Panel, Toast } from "../../shared/ui-kit/index.ts"
import { ProjectRegistrationForm } from "../../features/project-management/ProjectRegistrationForm.tsx"
import { TaskMenu } from "../../features/project-management/TaskMenu.tsx"
import { useRegisterProject } from "../../features/project-management/useRegisterProject.ts"
import { useTasks } from "../../features/project-management/useTasks.ts"
import "./HomePage.css"

export function HomePage() {
  const registration = useRegisterProject()
  const tasks = useTasks()

  return (
    <section>
      <div className="home-heading">
        <div>
          <h1>Projects and repositories</h1>
          <p>
            Continuous autonomous supervision of quality attributes under <strong>ISO/IEC 25010</strong>:
            Performance, Maintainability, Operational Security and Functional Adequacy.
          </p>
        </div>
      </div>
      <Panel>
        <ProjectRegistrationForm registration={registration} />
      </Panel>
      <div className="dock">
        {registration.state === "success" && (
          <Toast kind="success" message={registration.message} onClose={() => registration.reset()} />
        )}
        {registration.state === "error" && (
          <Toast kind="error" message={registration.message} onClose={() => registration.reset()} />
        )}
        <TaskMenu tasks={tasks} />
      </div>
    </section>
  )
}

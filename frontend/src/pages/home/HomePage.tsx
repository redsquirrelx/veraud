import { useEffect, useRef } from "react"
import { Panel } from "../../shared/ui-kit/index.ts"
import { ProjectList } from "../../features/project-management/ProjectList.tsx"
import { ProjectRegistrationForm } from "../../features/project-management/ProjectRegistrationForm.tsx"
import { useProjects } from "../../features/project-management/useProjects.ts"
import { useRegisterProject } from "../../features/project-management/useRegisterProject.ts"
import { useToasts } from "../../app/use-toasts.ts"
import "./HomePage.css"

export function HomePage() {
  const listing = useProjects()
  const registration = useRegisterProject({
    onRegistered: () => void listing.refresh(),
  })
  const { pushToast } = useToasts()
  const notified = useRef("")

  useEffect(() => {
    if (registration.message === "") {
      notified.current = ""
      return
    }
    if (registration.state === "success" || registration.state === "error") {
      const key = `${registration.state}:${registration.message}`
      if (notified.current !== key) {
        notified.current = key
        pushToast(registration.state, registration.message)
      }
    }
  }, [registration.state, registration.message, pushToast])

  return (
    <section className="page">
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
      <ProjectList listing={listing} />
    </section>
  )
}

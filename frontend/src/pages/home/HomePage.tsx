import { useEffect, useRef, useState } from "react"
import { useTranslation, Trans } from "react-i18next"
import { Checkbox, Panel } from "../../shared/ui-kit/index.ts"
import { ProjectList } from "../../features/project-management/ProjectList.tsx"
import { ProjectRegistrationForm } from "../../features/project-management/ProjectRegistrationForm.tsx"
import { useProjects } from "../../features/project-management/useProjects.ts"
import { useRegisterProject } from "../../features/project-management/useRegisterProject.ts"
import { useToasts } from "../../app/use-toasts.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import "./HomePage.css"

const SHALLOW_CLONE_KEY = "projects.shallowClone"

export function HomePage() {
  const { t } = useTranslation("projects")
  const [shallowClone, setShallowClone] = useState(() => {
    const stored = localStorage.get<unknown>(SHALLOW_CLONE_KEY, null)
    if (typeof stored === "boolean") return stored
    return localStorage.get<unknown>("projects.cloneFullRepository", false) !== true
  })
  const listing = useProjects()
  const registration = useRegisterProject({
    shallowClone,
    onRegistered: () => void listing.refresh(),
  })
  const { pushToast } = useToasts()
  const notified = useRef("")

  useEffect(() => {
    localStorage.set(SHALLOW_CLONE_KEY, shallowClone)
    localStorage.remove("projects.cloneFullRepository")
  }, [shallowClone])

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
          <h1>{t("home.title")}</h1>
          <p>
            <Trans ns="projects" i18nKey="home.description" components={{ strong: <strong /> }} />
          </p>
        </div>
      </div>
      <Panel>
        <ProjectRegistrationForm registration={registration} />
        <div className="home-clone-options">
          <Checkbox label={t("home.shallowClone")} checked={shallowClone} onChange={setShallowClone} />
        </div>
      </Panel>
      <ProjectList listing={listing} />
    </section>
  )
}

import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ApiError, deleteProject, type ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import { useToasts } from "../../app/use-toasts.ts"
import { Button, Card, Modal, TextInput } from "../../shared/ui-kit/index.ts"
import "./ProjectSettingsSection.css"

interface ProjectSettingsSectionProps {
  project: ProjectSummary
}

/** "Project Settings": read-only danger zone with the only destructive action of
 *  the project — irreversible deletion, gated by typing the repository slug. */
export function ProjectSettingsSection({ project }: ProjectSettingsSectionProps) {
  const { t } = useTranslation("projects")
  const navigate = useNavigate()
  const { pushToast } = useToasts()
  const repoFullName = `${project.repositoryOwner}/${project.repositoryName}`
  const [modalOpen, setModalOpen] = useState(false)
  const [typed, setTyped] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [pending, setPending] = useState<number[] | null>(null)

  function openModal() {
    setTyped("")
    setError("")
    setPending(null)
    setModalOpen(true)
  }

  function closeModal() {
    if (!busy) setModalOpen(false)
  }

  async function confirmDelete() {
    setBusy(true)
    setError("")
    try {
      const outcome = await deleteProject(project.id)
      if (outcome.status === "cancelling") {
        setPending(outcome.pendingExecutionIds)
        pushToast("info", t("detail.projectSettings.cancellingToast", { count: outcome.pendingExecutionIds.length }))
        return
      }
      const withWarnings = outcome.disk.artifactFailures.length + (outcome.disk.cloneFailure === null ? 0 : 1) + outcome.disk.artifactsSkipped
      if (withWarnings > 0) {
        pushToast("error", t("detail.projectSettings.deletedWithWarnings", { count: withWarnings }))
      } else {
        pushToast("success", t("detail.projectSettings.deleted"))
      }
      navigate("/")
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 404) {
        pushToast("info", t("detail.projectSettings.alreadyDeleted"))
        navigate("/")
        return
      }
      const detail = failure instanceof ApiError && failure.messageSource !== "client" ? failure.message : undefined
      const message = detail === undefined ? t("detail.projectSettings.deleteFailed") : t("detail.projectSettings.deleteFailedWithDetail", { detail })
      setError(message)
      pushToast("error", message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="project-body-card project-settings-card" layout="stack" gap="md" align="stretch" padding="responsive">
      <section className="project-settings" aria-label={t("detail.projectSettings.regionLabel")}>
        <h2>{t("detail.projectSettings.title")}</h2>
        <div className="project-danger-zone">
          <h3>{t("detail.projectSettings.dangerZoneTitle")}</h3>
          <p>{t("detail.projectSettings.dangerZoneDescription")}</p>
          <ul className="project-danger-list">
            <li>{t("detail.projectSettings.whatDeleted.clone", { target: repoFullName })}</li>
            <li>{t("detail.projectSettings.whatDeleted.history")}</li>
            <li>{t("detail.projectSettings.whatDeleted.artifacts")}</li>
            <li>{t("detail.projectSettings.whatDeleted.databaseNote")}</li>
          </ul>
          <Button variant="danger" onClick={openModal}>{t("detail.projectSettings.deleteButton")}</Button>
        </div>
      </section>

      <Modal open={modalOpen} label={t("detail.projectSettings.deleteModalTitle")} title={t("detail.projectSettings.deleteModalTitle")} onClose={closeModal}>
        <div className="project-delete-modal">
          <p>{t("detail.projectSettings.deleteModalDescription", { target: repoFullName })}</p>
          <TextInput label={t("detail.projectSettings.typeToConfirm", { target: repoFullName })} placeholder={repoFullName} value={typed} onChange={setTyped} disabled={busy} />
          {pending !== null && <p role="status" className="project-delete-cancelling">{t("detail.projectSettings.cancellingDescription", { count: pending.length })}</p>}
          {error !== "" && <p role="alert" className="project-delete-error">{error}</p>}
          <div className="project-delete-actions">
            <Button variant="secondary" onClick={closeModal} disabled={busy}>{t("detail.projectSettings.cancel")}</Button>
            <Button variant="danger" loading={busy} loadingText={t("detail.projectSettings.deleting")} disabled={typed !== repoFullName} onClick={() => void confirmDelete()}>{t("detail.projectSettings.confirmButton")}</Button>
          </div>
        </div>
      </Modal>
    </Card>
  )
}

import { useId, useState, type FormEvent, type KeyboardEvent } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { Button, Card, ItemList, ItemSelector, Modal, PlusIcon, TextInput, type ItemSelectorItem } from "../../shared/ui-kit/index.ts"
import { useToasts } from "../../app/use-toasts.ts"
import { useAiProviders } from "../../features/llm-management/useAiProviders.ts"
import { TASK_KIND_OPTIONS, useTaskVisibility } from "../../shared/task-manager/index.ts"
import { ModelListItem } from "./ModelListItem.tsx"
import { CredentialListItem } from "./CredentialListItem.tsx"
import { LanguageSelector } from "./LanguageSelector.tsx"
import { AgentsSettings } from "./AgentsSettings.tsx"
import { AuditSettings } from "./AuditSettings.tsx"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import "./SettingsPage.css"

const settingsTabs = [
  { id: "agents", labelKey: "tabs.agents" },
  { id: "audit", labelKey: "tabs.audit" },
  { id: "models", labelKey: "tabs.models" },
  { id: "preferences", labelKey: "tabs.preferences" },
] as const
type SettingsTab = typeof settingsTabs[number]["id"]
const settingsTabStorageKey = "settings.activeTab"

// Task-kind labels live in the settings namespace (translated at render so
// they follow language changes). Unknown kinds fall back to the raw
// TASK_KIND_OPTIONS text, which stays in English.
const taskKindTextKeys = {
  "clone": { labelKey: "preferences.taskKinds.clone.label", hintKey: "preferences.taskKinds.clone.hint" },
  "pull": { labelKey: "preferences.taskKinds.pull.label", hintKey: "preferences.taskKinds.pull.hint" },
  "fetch": { labelKey: "preferences.taskKinds.fetch.label", hintKey: "preferences.taskKinds.fetch.hint" },
  "checkout-branch": { labelKey: "preferences.taskKinds.checkoutBranch.label", hintKey: "preferences.taskKinds.checkoutBranch.hint" },
  "checkout-detach": { labelKey: "preferences.taskKinds.checkoutDetach.label", hintKey: "preferences.taskKinds.checkoutDetach.hint" },
  "list-branches": { labelKey: "preferences.taskKinds.listBranches.label", hintKey: "preferences.taskKinds.listBranches.hint" },
  "rev-parse": { labelKey: "preferences.taskKinds.revParse.label", hintKey: "preferences.taskKinds.revParse.hint" },
  "log-commits": { labelKey: "preferences.taskKinds.logCommits.label", hintKey: "preferences.taskKinds.logCommits.hint" },
} as const

// Frontend-owned errors are stored as translation keys (plus the backend
// detail, when any) so they follow language changes instead of freezing the
// language active when the failure happened.
interface SettingsFormError {
  key: ParseKeys<"settings">
  detail?: string
}

export function SettingsPage() {
  const { t } = useTranslation("settings")
  const tabsId = useId()
  const [activeTab, setActiveTab] = useState<SettingsTab>(() => {
    const saved = localStorage.get<unknown>(settingsTabStorageKey, "models")
    return settingsTabs.find((tab) => tab.id === saved)?.id ?? "models"
  })
  function selectTab(tab: SettingsTab) {
    setActiveTab(tab)
    localStorage.set(settingsTabStorageKey, tab)
  }
  const [visibility, update] = useTaskVisibility()
  const { providers, loading, loadError, refresh, addModel, editModel, removeModel, addCredential, editCredential, removeCredential } = useAiProviders()
  const { pushToast } = useToasts()
  const [modelId, setModelId] = useState<string[]>([])
  const [credentialId, setCredentialId] = useState<string[]>([])
  const [modal, setModal] = useState<"model" | "credential" | null>(null)
  const [editingModelId, setEditingModelId] = useState<number | null>(null)
  const [editingCredentialId, setEditingCredentialId] = useState<number | null>(null)
  const [modelProvider, setModelProvider] = useState<string | null>(null)
  const [modelName, setModelName] = useState("")
  const [modelError, setModelError] = useState<SettingsFormError | null>(null)
  const [credentialProvider, setCredentialProvider] = useState<string | null>(null)
  const [credentialName, setCredentialName] = useState("")
  const [credentialKey, setCredentialKey] = useState("")
  const [credentialError, setCredentialError] = useState<SettingsFormError | null>(null)

  // useAiProviders reports the backend message verbatim. That hook always
  // throws the fixed "Could not load AI providers" string, so any loadError
  // matching the translated generic is shown as-is; anything else is kept as
  // technical detail alongside the translated generic message.
  const providersLoadError = loadError === ""
    ? ""
    : loadError === t("models.loadFailed")
      ? t("models.loadFailed")
      : `${t("models.loadFailed")}: ${loadError}`

  const models = providers.flatMap((provider) => provider.models.map((model) => ({ ...model, providerId: provider.id, provider: provider.name })))
  const credentials = providers.flatMap((provider) => provider.credentials.map((credential) => ({ ...credential, providerId: provider.id, provider: provider.name })))
  const providerOptions: ItemSelectorItem[] = providers.map((provider) => ({ id: String(provider.id), label: provider.name }))

  const canSubmitModel = modelProvider !== null && modelName.trim() !== ""
  const canSubmitCredential = credentialProvider !== null && credentialName.trim() !== "" && (editingCredentialId !== null || credentialKey.trim() !== "")

  function openModelModal() {
    setEditingModelId(null)
    setModelProvider(null)
    setModelName("")
    setModelError(null)
    setModal("model")
  }

  function openCredentialModal() {
    setEditingCredentialId(null)
    setCredentialProvider(null)
    setCredentialName("")
    setCredentialKey("")
    setCredentialError(null)
    setModal("credential")
  }

  function openEditModel(providerId: number, id: number, name: string) {
    setEditingModelId(id)
    setModelProvider(String(providerId))
    setModelName(name)
    setModelError(null)
    setModal("model")
  }

  function openEditCredential(providerId: number, id: number, name: string) {
    setEditingCredentialId(id)
    setCredentialProvider(String(providerId))
    setCredentialName(name)
    setCredentialKey("")
    setCredentialError(null)
    setModal("credential")
  }

  async function submitModel(event: FormEvent) {
    event.preventDefault()
    if (!canSubmitModel || modelProvider === null) {
      return
    }
    try {
      if (editingModelId === null) {
        await addModel(Number(modelProvider), modelName.trim())
        pushToast("success", t("models.registered", { name: modelName.trim() }))
      } else {
        await editModel(Number(modelProvider), editingModelId, modelName.trim())
        pushToast("success", t("models.updated", { name: modelName.trim() }))
      }
      setModelName("")
      setModelError(null)
      setModal(null)
    } catch (failure) {
      // Backend details are kept verbatim (the English template renders the
      // detail unchanged so it stays findable); other failures use the
      // translated generic message.
      const key = failure instanceof ApiError
        ? editingModelId === null ? "models.registerFailedWithDetail" : "models.updateFailedWithDetail"
        : editingModelId === null ? "models.registerFailed" : "models.updateFailed"
      const detail = failure instanceof ApiError ? failure.message : undefined
      setModelError(detail === undefined ? { key } : { key, detail })
      pushToast("error", detail === undefined ? t(key) : t(key, { detail }))
    }
  }

  async function submitCredential(event: FormEvent) {
    event.preventDefault()
    if (!canSubmitCredential || credentialProvider === null) {
      return
    }
    try {
      if (editingCredentialId === null) {
        await addCredential(Number(credentialProvider), credentialName.trim(), credentialKey.trim())
        pushToast("success", t("credentials.registered", { name: credentialName.trim() }))
      } else {
        await editCredential(Number(credentialProvider), editingCredentialId, credentialName.trim(), credentialKey.trim() || undefined)
        pushToast("success", t("credentials.updated", { name: credentialName.trim() }))
      }
      setCredentialName("")
      setCredentialKey("")
      setCredentialError(null)
      setModal(null)
    } catch (failure) {
      const key = failure instanceof ApiError
        ? editingCredentialId === null ? "credentials.registerFailedWithDetail" : "credentials.updateFailedWithDetail"
        : editingCredentialId === null ? "credentials.registerFailed" : "credentials.updateFailed"
      const detail = failure instanceof ApiError ? failure.message : undefined
      setCredentialError(detail === undefined ? { key } : { key, detail })
      pushToast("error", detail === undefined ? t(key) : t(key, { detail }))
    }
  }

  async function deleteModel(providerId: number, id: number, name: string) {
    try {
      await removeModel(providerId, id)
      setModelId((current) => current.filter((entry) => entry !== String(id)))
      pushToast("success", t("models.deleted", { name }))
    } catch (failure) {
      pushToast("error", failure instanceof ApiError ? t("models.deleteFailedWithDetail", { detail: failure.message }) : t("models.deleteFailed"))
    }
  }

  async function deleteCredential(providerId: number, id: number, name: string) {
    try {
      await removeCredential(providerId, id)
      setCredentialId((current) => current.filter((entry) => entry !== String(id)))
      pushToast("success", t("credentials.deleted", { name }))
    } catch (failure) {
      pushToast("error", failure instanceof ApiError ? t("credentials.deleteFailedWithDetail", { detail: failure.message }) : t("credentials.deleteFailed"))
    }
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
    event.preventDefault()
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? settingsTabs.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + settingsTabs.length) % settingsTabs.length
    const nextTab = settingsTabs[nextIndex]!
    selectTab(nextTab.id)
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]?.focus()
  }

  function renderFormError(error: SettingsFormError | null) {
    if (error === null) {
      return null
    }
    return <p className="settings-error">{error.detail === undefined ? t(error.key) : t(error.key, { detail: error.detail })}</p>
  }

  return (
    <section className="settings-page">
      <div className="home-heading">
        <div>
          <h1>{t("title")}</h1>
        </div>
      </div>
      <div className="settings-tabs" role="tablist" aria-label={t("tabs.label")}>
        {settingsTabs.map((tab, index) => (
          <button
            key={tab.id}
            id={`${tabsId}-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`${tabsId}-panel-${tab.id}`}
            tabIndex={activeTab === tab.id ? 0 : -1}
            onClick={() => selectTab(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${tabsId}-panel-agents`} aria-labelledby={`${tabsId}-tab-agents`} hidden={activeTab !== "agents"} tabIndex={0}>
        {activeTab === "agents" && <AgentsSettings providers={providers} providersLoading={loading} providersError={providersLoadError} onAssignmentsSaved={(agent) => {
          pushToast("success", t("agents.assignmentsSaved", { agentType: agent.agentType }))
          void refresh()
        }} />}
      </div>
      <div role="tabpanel" id={`${tabsId}-panel-audit`} aria-labelledby={`${tabsId}-tab-audit`} hidden={activeTab !== "audit"} tabIndex={0}>
        {activeTab === "audit" && <>
          <AgentsSettings providers={providers} providersLoading={loading} providersError={providersLoadError}
            agentTypes={["maintainability_manager", "security"]}
            modelAccessOnly
            heading={t("audit.modelsTitle")}
            description={t("audit.modelsDescription")}
            labels={{ maintainability_manager: t("audit.allAgents"), security: t("audit.security") }}
            onAssignmentsSaved={() => { pushToast("success", t("audit.saved")); void refresh() }} />
          <AuditSettings />
        </>}
      </div>
      <div role="tabpanel" id={`${tabsId}-panel-models`} aria-labelledby={`${tabsId}-tab-models`} hidden={activeTab !== "models"} tabIndex={0}>
      <Card>
        <span className="label">{t("models.sectionTitle")}</span>
        <p className="settings-hint">{t("credentials.editHint")}</p>
        {providersLoadError !== "" ? (
          <p className="settings-error">{providersLoadError}</p>
        ) : (
          <>
            <div className="settings-llm-row">
              <div className="settings-llm-group">
                <div className="settings-llm-head">
                  <Button variant="primary" square ariaLabel={t("models.add")} title={t("models.add")} onClick={openModelModal}>
                    <PlusIcon />
                  </Button>
                  <span className="label">{t("models.title")}</span>
                </div>
                <ItemList
                  items={models.map((model) => ({ id: String(model.id), name: model.name }))}
                  selectedIds={modelId}
                  onSelectionChange={setModelId}
                  mode="single"
                  loading={loading}
                  emptyText={t("models.empty")}
                  renderItem={(entry) => {
                    const model = models.find((candidate) => String(candidate.id) === entry.id)
                    if (model === undefined) {
                      return null
                    }
                    return (
                      <ModelListItem
                        name={model.name}
                        provider={model.provider}
                        inUse={model.inUse}
                        onEdit={() => openEditModel(model.providerId, model.id, model.name)}
                        onRemove={() => void deleteModel(model.providerId, model.id, model.name)}
                      />
                    )
                  }}
                />
              </div>
              <div className="settings-llm-group">
                <div className="settings-llm-head">
                  <Button variant="primary" square ariaLabel={t("credentials.add")} title={t("credentials.add")} onClick={openCredentialModal}>
                    <PlusIcon />
                  </Button>
                  <span className="label">{t("credentials.title")}</span>
                </div>
                <ItemList
                  items={credentials.map((credential) => ({ id: String(credential.id), name: credential.name }))}
                  selectedIds={credentialId}
                  onSelectionChange={setCredentialId}
                  mode="single"
                  loading={loading}
                  emptyText={t("credentials.empty")}
                  renderItem={(entry) => {
                    const credential = credentials.find((candidate) => String(candidate.id) === entry.id)
                    if (credential === undefined) {
                      return null
                    }
                    return (
                      <CredentialListItem
                        name={credential.name}
                        provider={credential.provider}
                        apiKeyPreview={credential.apiKeyPreview}
                        inUse={credential.inUse}
                        onEdit={() => openEditCredential(credential.providerId, credential.id, credential.name)}
                        onRemove={() => void deleteCredential(credential.providerId, credential.id, credential.name)}
                      />
                    )
                  }}
                />
              </div>
            </div>
          </>
        )}
      </Card>
      </div>
      <div role="tabpanel" id={`${tabsId}-panel-preferences`} aria-labelledby={`${tabsId}-tab-preferences`} hidden={activeTab !== "preferences"} tabIndex={0}>
      <Card>
        <LanguageSelector />
      </Card>
      <Card>
        <span className="label">{t("preferences.notifications.title")}</span>
        <p className="settings-hint">{t("preferences.notifications.hint")}</p>
        <div className="settings-tasks">
          {TASK_KIND_OPTIONS.map((option) => {
            const textKeys = taskKindTextKeys[option.kind as keyof typeof taskKindTextKeys]
            return (
            <label key={option.kind} className="settings-task">
              <input
                type="checkbox"
                checked={visibility[option.kind] ?? true}
                onChange={(event) => update(option.kind, event.target.checked)}
              />
              <span className="mono">{textKeys ? t(textKeys.labelKey) : option.label}</span>
              <span className="label">{textKeys ? t(textKeys.hintKey) : option.hint}</span>
            </label>
            )
          })}
        </div>
      </Card>
      </div>
      <Modal open={modal === "model"} label={editingModelId === null ? t("models.addDialog") : t("models.editDialog")} title={editingModelId === null ? t("models.addDialog") : t("models.editDialog")} size="narrow" onClose={() => setModal(null)}>
        <form className="settings-modal-form" onSubmit={(event) => void submitModel(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={modelProvider}
            onSelect={setModelProvider}
            disabled={editingModelId !== null}
            hasMore={false}
            onLoadMore={() => {}}
            label={t("form.provider")}
            placeholder={t("form.providerPlaceholder")}
          />
          <TextInput value={modelName} label={t("models.form.name")} placeholder={t("models.form.namePlaceholder")} onChange={setModelName} />
          {renderFormError(modelError)}
          <Button type="submit" disabled={!canSubmitModel}>
            {editingModelId === null ? t("form.submit") : t("form.edit")}
          </Button>
        </form>
      </Modal>
      <Modal open={modal === "credential"} label={editingCredentialId === null ? t("credentials.addDialog") : t("credentials.editDialog")} title={editingCredentialId === null ? t("credentials.addDialog") : t("credentials.editDialog")} size="narrow" onClose={() => setModal(null)}>
        <form className="settings-modal-form" onSubmit={(event) => void submitCredential(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={credentialProvider}
            onSelect={setCredentialProvider}
            disabled={editingCredentialId !== null}
            hasMore={false}
            onLoadMore={() => {}}
            label={t("form.provider")}
            placeholder={t("form.providerPlaceholder")}
          />
          <TextInput value={credentialName} label={t("credentials.form.name")} placeholder={t("credentials.form.namePlaceholder")} onChange={setCredentialName} />
          <TextInput value={credentialKey} label={t("credentials.form.apiKey")} type="password" onChange={setCredentialKey} />
          {renderFormError(credentialError)}
          <Button type="submit" disabled={!canSubmitCredential}>
            {editingCredentialId === null ? t("form.submit") : t("form.edit")}
          </Button>
        </form>
      </Modal>
    </section>
  )
}

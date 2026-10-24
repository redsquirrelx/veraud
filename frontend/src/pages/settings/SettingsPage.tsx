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

type SettingsEditorBase = {
  id: number | null
  providerId: string | null
  name: string
  error: SettingsFormError | null
}

type SettingsEditor =
  | (SettingsEditorBase & { kind: "model" })
  | (SettingsEditorBase & { kind: "credential", apiKey: string })

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
  const [editor, setEditor] = useState<SettingsEditor | null>(null)

  // useAiProviders reports the backend message verbatim. That hook always
  // throws the fixed "Could not load AI providers" string, so any loadError
  // matching the translated generic is shown as-is; anything else is kept as
  // technical detail alongside the translated generic message.
  const providersLoadError = loadError === ""
    ? ""
    : loadError === t("models.loadFailed")
      ? t("models.loadFailed")
      : `${t("models.loadFailed")}: ${loadError}`

  const models = providers.flatMap((provider) => provider.models.map((model) => ({ ...model,
    id: String(model.id), resourceId: model.id, providerId: provider.id, provider: provider.name })))
  const credentials = providers.flatMap((provider) => provider.credentials.map((credential) => ({ ...credential,
    id: String(credential.id), resourceId: credential.id, providerId: provider.id, provider: provider.name })))
  const providerOptions: ItemSelectorItem[] = providers.map((provider) => ({ id: String(provider.id), label: provider.name }))

  const canSubmitEditor = editor !== null && editor.providerId !== null && editor.name.trim() !== ""
    && (editor.kind === "model" || editor.id !== null || editor.apiKey.trim() !== "")

  function openEditor(kind: "model" | "credential", resource?: { id: number, providerId: number, name: string }) {
    const base: SettingsEditorBase = {
      id: resource?.id ?? null,
      providerId: resource ? String(resource.providerId) : null,
      name: resource?.name ?? "",
      error: null,
    }
    setEditor(kind === "model" ? { ...base, kind } : { ...base, kind, apiKey: "" })
  }

  async function submitEditor(event: FormEvent) {
    event.preventDefault()
    const current = editor
    if (!canSubmitEditor || current === null || current.providerId === null) {
      return
    }
    const providerId = Number(current.providerId)
    const name = current.name.trim()
    try {
      if (current.kind === "model" && current.id === null) {
        await addModel(providerId, name)
        pushToast("success", t("models.registered", { name }))
      } else if (current.kind === "model") {
        await editModel(providerId, current.id!, name)
        pushToast("success", t("models.updated", { name }))
      } else if (current.id === null) {
        await addCredential(providerId, name, current.apiKey.trim())
        pushToast("success", t("credentials.registered", { name }))
      } else {
        await editCredential(providerId, current.id, name, current.apiKey.trim() || undefined)
        pushToast("success", t("credentials.updated", { name }))
      }
      setEditor(null)
    } catch (failure) {
      const editing = current.id !== null
      const keys: Record<"create" | "createDetail" | "update" | "updateDetail", ParseKeys<"settings">> = current.kind === "model"
        ? { create: "models.registerFailed", createDetail: "models.registerFailedWithDetail", update: "models.updateFailed", updateDetail: "models.updateFailedWithDetail" }
        : { create: "credentials.registerFailed", createDetail: "credentials.registerFailedWithDetail", update: "credentials.updateFailed", updateDetail: "credentials.updateFailedWithDetail" }
      const key: ParseKeys<"settings"> = failure instanceof ApiError
        ? editing ? keys.updateDetail : keys.createDetail
        : editing ? keys.update : keys.create
      const detail = failure instanceof ApiError ? failure.message : undefined
      const formError: SettingsFormError = detail === undefined ? { key } : { key, detail }
      setEditor((latest) => latest?.kind === current.kind && latest.id === current.id ? { ...latest, error: formError } : latest)
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

  const editorDialogKey = editor === null ? null : editor.kind === "model"
    ? editor.id === null ? "models.addDialog" : "models.editDialog"
    : editor.id === null ? "credentials.addDialog" : "credentials.editDialog"

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
            qualityCategories
            modelAccessOnly
            heading={t("audit.modelsTitle")}
            description={t("audit.modelsDescription")}
            labels={{ maintainability: t("audit.allAgents"), security: t("audit.security"), functional_adequacy: t("audit.functionalAdequacy") }}
            onAssignmentsSaved={() => { pushToast("success", t("audit.saved")); void refresh() }} />
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
                  <Button variant="primary" square ariaLabel={t("models.add")} title={t("models.add")} onClick={() => openEditor("model")}>
                    <PlusIcon />
                  </Button>
                  <span className="label">{t("models.title")}</span>
                </div>
                <ItemList
                  items={models}
                  selectedIds={modelId}
                  onSelectionChange={setModelId}
                  mode="single"
                  loading={loading}
                  emptyText={t("models.empty")}
                  renderItem={(model) => <ModelListItem
                    name={model.name}
                    provider={model.provider}
                    inUse={model.inUse}
                    onEdit={() => openEditor("model", { id: model.resourceId, providerId: model.providerId, name: model.name })}
                    onRemove={() => void deleteModel(model.providerId, model.resourceId, model.name)}
                  />}
                />
              </div>
              <div className="settings-llm-group">
                <div className="settings-llm-head">
                  <Button variant="primary" square ariaLabel={t("credentials.add")} title={t("credentials.add")} onClick={() => openEditor("credential")}>
                    <PlusIcon />
                  </Button>
                  <span className="label">{t("credentials.title")}</span>
                </div>
                <ItemList
                  items={credentials}
                  selectedIds={credentialId}
                  onSelectionChange={setCredentialId}
                  mode="single"
                  loading={loading}
                  emptyText={t("credentials.empty")}
                  renderItem={(credential) => <CredentialListItem
                    name={credential.name}
                    provider={credential.provider}
                    apiKeyPreview={credential.apiKeyPreview}
                    inUse={credential.inUse}
                    onEdit={() => openEditor("credential", { id: credential.resourceId, providerId: credential.providerId, name: credential.name })}
                    onRemove={() => void deleteCredential(credential.providerId, credential.resourceId, credential.name)}
                  />}
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
      <Modal open={editor !== null} label={editorDialogKey === null ? "" : t(editorDialogKey)}
        title={editorDialogKey === null ? "" : t(editorDialogKey)} size="narrow" onClose={() => setEditor(null)}>
        {editor !== null && <form className="settings-modal-form" onSubmit={(event) => void submitEditor(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={editor.providerId}
            onSelect={(providerId) => setEditor((current) => current ? { ...current, providerId } : current)}
            disabled={editor.id !== null}
            hasMore={false}
            onLoadMore={() => {}}
            label={t("form.provider")}
            placeholder={t("form.providerPlaceholder")}
          />
          <TextInput
            value={editor.name}
            label={t(editor.kind === "model" ? "models.form.name" : "credentials.form.name")}
            placeholder={t(editor.kind === "model" ? "models.form.namePlaceholder" : "credentials.form.namePlaceholder")}
            onChange={(name) => setEditor((current) => current ? { ...current, name } : current)}
          />
          {editor.kind === "credential" && <TextInput value={editor.apiKey} label={t("credentials.form.apiKey")} type="password"
            onChange={(apiKey) => setEditor((current) => current?.kind === "credential" ? { ...current, apiKey } : current)} />}
          {renderFormError(editor.error)}
          <Button type="submit" disabled={!canSubmitEditor}>{editor.id === null ? t("form.submit") : t("form.edit")}</Button>
        </form>}
      </Modal>
    </section>
  )
}

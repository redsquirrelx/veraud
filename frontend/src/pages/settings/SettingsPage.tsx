import { useState, type FormEvent } from "react"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { Button, Card, ItemList, ItemSelector, Modal, PlusIcon, TextInput, type ItemSelectorItem } from "../../shared/ui-kit/index.ts"
import { useToasts } from "../../app/use-toasts.ts"
import { useAiProviders } from "../../features/llm-management/useAiProviders.ts"
import { TASK_KIND_OPTIONS, useTaskVisibility } from "../../shared/task-manager/index.ts"
import { ModelListItem } from "./ModelListItem.tsx"
import { CredentialListItem } from "./CredentialListItem.tsx"
import "./SettingsPage.css"

export function SettingsPage() {
  const [visibility, update] = useTaskVisibility()
  const { providers, loading, loadError, addModel, editModel, removeModel, addCredential, editCredential, removeCredential } = useAiProviders()
  const { pushToast } = useToasts()
  const [modelId, setModelId] = useState<string[]>([])
  const [credentialId, setCredentialId] = useState<string[]>([])
  const [modal, setModal] = useState<"model" | "credential" | null>(null)
  const [editingModelId, setEditingModelId] = useState<number | null>(null)
  const [editingCredentialId, setEditingCredentialId] = useState<number | null>(null)
  const [modelProvider, setModelProvider] = useState<string | null>(null)
  const [modelName, setModelName] = useState("")
  const [modelError, setModelError] = useState("")
  const [credentialProvider, setCredentialProvider] = useState<string | null>(null)
  const [credentialName, setCredentialName] = useState("")
  const [credentialKey, setCredentialKey] = useState("")
  const [credentialError, setCredentialError] = useState("")

  const models = providers.flatMap((provider) => provider.models.map((model) => ({ ...model, providerId: provider.id, provider: provider.name })))
  const credentials = providers.flatMap((provider) => provider.credentials.map((credential) => ({ ...credential, providerId: provider.id, provider: provider.name })))
  const providerOptions: ItemSelectorItem[] = providers.map((provider) => ({ id: String(provider.id), label: provider.name }))

  const canSubmitModel = modelProvider !== null && modelName.trim() !== ""
  const canSubmitCredential = credentialProvider !== null && credentialName.trim() !== "" && (editingCredentialId !== null || credentialKey.trim() !== "")

  function openModelModal() {
    setEditingModelId(null)
    setModelProvider(null)
    setModelName("")
    setModelError("")
    setModal("model")
  }

  function openCredentialModal() {
    setEditingCredentialId(null)
    setCredentialProvider(null)
    setCredentialName("")
    setCredentialKey("")
    setCredentialError("")
    setModal("credential")
  }

  function openEditModel(providerId: number, id: number, name: string) {
    setEditingModelId(id)
    setModelProvider(String(providerId))
    setModelName(name)
    setModelError("")
    setModal("model")
  }

  function openEditCredential(providerId: number, id: number, name: string) {
    setEditingCredentialId(id)
    setCredentialProvider(String(providerId))
    setCredentialName(name)
    setCredentialKey("")
    setCredentialError("")
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
        pushToast("success", `Model ${modelName.trim()} registered`)
      } else {
        await editModel(Number(modelProvider), editingModelId, modelName.trim())
        pushToast("success", `Model ${modelName.trim()} updated`)
      }
      setModelName("")
      setModelError("")
      setModal(null)
    } catch (failure) {
      const message = failure instanceof ApiError ? failure.message : editingModelId === null ? "Could not register the model" : "Could not update the model"
      setModelError(message)
      pushToast("error", message)
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
        pushToast("success", `Credential ${credentialName.trim()} registered`)
      } else {
        await editCredential(Number(credentialProvider), editingCredentialId, credentialName.trim(), credentialKey.trim() || undefined)
        pushToast("success", `Credential ${credentialName.trim()} updated`)
      }
      setCredentialName("")
      setCredentialKey("")
      setCredentialError("")
      setModal(null)
    } catch (failure) {
      const message = failure instanceof ApiError ? failure.message : editingCredentialId === null ? "Could not register the credential" : "Could not update the credential"
      setCredentialError(message)
      pushToast("error", message)
    }
  }

  async function deleteModel(providerId: number, id: number, name: string) {
    try {
      await removeModel(providerId, id)
      setModelId((current) => current.filter((entry) => entry !== String(id)))
      pushToast("success", `Model ${name} deleted`)
    } catch (failure) {
      pushToast("error", failure instanceof ApiError ? failure.message : "Could not delete the model")
    }
  }

  async function deleteCredential(providerId: number, id: number, name: string) {
    try {
      await removeCredential(providerId, id)
      setCredentialId((current) => current.filter((entry) => entry !== String(id)))
      pushToast("success", `Credential ${name} deleted`)
    } catch (failure) {
      pushToast("error", failure instanceof ApiError ? failure.message : "Could not delete the credential")
    }
  }

  return (
    <section className="settings-page">
      <div className="home-heading">
        <div>
          <h1>General settings</h1>
        </div>
      </div>
      <Card>
        <span className="label">Models & credentials</span>
        <p className="settings-hint">When editing a credential, leave the API key blank to keep the current key.</p>
        {loadError !== "" ? (
          <p className="settings-error">{loadError}</p>
        ) : (
          <>
            <div className="settings-llm-row">
              <div className="settings-llm-group">
                <div className="settings-llm-head">
                  <Button variant="primary" square ariaLabel="Add model" title="Add model" onClick={openModelModal}>
                    <PlusIcon />
                  </Button>
                  <span className="label">Models</span>
                </div>
                <ItemList
                  items={models.map((model) => ({ id: String(model.id), name: model.name }))}
                  selectedIds={modelId}
                  onSelectionChange={setModelId}
                  mode="single"
                  loading={loading}
                  emptyText="No models registered yet"
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
                  <Button variant="primary" square ariaLabel="Add credential" title="Add credential" onClick={openCredentialModal}>
                    <PlusIcon />
                  </Button>
                  <span className="label">Credentials</span>
                </div>
                <ItemList
                  items={credentials.map((credential) => ({ id: String(credential.id), name: credential.name }))}
                  selectedIds={credentialId}
                  onSelectionChange={setCredentialId}
                  mode="single"
                  loading={loading}
                  emptyText="No credentials registered yet"
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

      <Card>
        <span className="label">Task notifications</span>
        <p className="settings-hint">Read-only tasks stay silent unless they fail. Failed tasks always show.</p>
        <div className="settings-tasks">
          {TASK_KIND_OPTIONS.map((option) => (
            <label key={option.kind} className="settings-task">
              <input
                type="checkbox"
                checked={visibility[option.kind] ?? true}
                onChange={(event) => update(option.kind, event.target.checked)}
              />
              <span className="mono">{option.label}</span>
              <span className="label">{option.hint}</span>
            </label>
          ))}
        </div>
      </Card>
      <Modal open={modal === "model"} label={editingModelId === null ? "Add a model" : "Edit a model"} title={editingModelId === null ? "Add a model" : "Edit a model"} size="narrow" onClose={() => setModal(null)}>
        <form className="settings-modal-form" onSubmit={(event) => void submitModel(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={modelProvider}
            onSelect={setModelProvider}
            disabled={editingModelId !== null}
            hasMore={false}
            onLoadMore={() => {}}
            label="Provider"
            placeholder="Select a provider..."
          />
          <TextInput value={modelName} label="Model name" placeholder="Insert the model name..." onChange={setModelName} />
          {modelError !== "" && <p className="settings-error">{modelError}</p>}
          <Button type="submit" disabled={!canSubmitModel}>
            {editingModelId === null ? "Submit" : "Edit"}
          </Button>
        </form>
      </Modal>
      <Modal open={modal === "credential"} label={editingCredentialId === null ? "Add a credential" : "Edit a credential"} title={editingCredentialId === null ? "Add a credential" : "Edit a credential"} size="narrow" onClose={() => setModal(null)}>
        <form className="settings-modal-form" onSubmit={(event) => void submitCredential(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={credentialProvider}
            onSelect={setCredentialProvider}
            disabled={editingCredentialId !== null}
            hasMore={false}
            onLoadMore={() => {}}
            label="Provider"
            placeholder="Select a provider..."
          />
          <TextInput value={credentialName} label="Credential name" placeholder="Insert a name...." onChange={setCredentialName} />
          <TextInput value={credentialKey} label="Api Key" type="password" onChange={setCredentialKey} />
          {credentialError !== "" && <p className="settings-error">{credentialError}</p>}
          <Button type="submit" disabled={!canSubmitCredential}>
            {editingCredentialId === null ? "Submit" : "Edit"}
          </Button>
        </form>
      </Modal>
    </section>
  )
}

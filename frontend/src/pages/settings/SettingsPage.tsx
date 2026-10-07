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
  const { providers, loading, loadError, addModel, removeModel, addCredential, removeCredential } = useAiProviders()
  const { pushToast } = useToasts()
  const [modelId, setModelId] = useState<string[]>([])
  const [credentialId, setCredentialId] = useState<string[]>([])
  const [modal, setModal] = useState<"model" | "credential" | null>(null)
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
  const canSubmitCredential = credentialProvider !== null && credentialName.trim() !== "" && credentialKey.trim() !== ""

  function openModelModal() {
    setModelError("")
    setModal("model")
  }

  function openCredentialModal() {
    setCredentialError("")
    setModal("credential")
  }

  async function submitModel(event: FormEvent) {
    event.preventDefault()
    if (!canSubmitModel || modelProvider === null) {
      return
    }
    try {
      await addModel(Number(modelProvider), modelName.trim())
      pushToast("success", `Model ${modelName.trim()} registered`)
      setModelName("")
      setModelError("")
      setModal(null)
    } catch (failure) {
      const message = failure instanceof ApiError ? failure.message : "Could not register the model"
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
      await addCredential(Number(credentialProvider), credentialName.trim(), credentialKey.trim())
      pushToast("success", `Credential ${credentialName.trim()} registered`)
      setCredentialName("")
      setCredentialKey("")
      setCredentialError("")
      setModal(null)
    } catch (failure) {
      const message = failure instanceof ApiError ? failure.message : "Could not register the credential"
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
      <Modal open={modal === "model"} label="Add a model" title="Add a model" size="narrow" onClose={() => setModal(null)}>
        <form className="settings-modal-form" onSubmit={(event) => void submitModel(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={modelProvider}
            onSelect={setModelProvider}
            hasMore={false}
            onLoadMore={() => {}}
            label="Provider"
            placeholder="Select a provider..."
          />
          <TextInput value={modelName} label="Model name" placeholder="Insert the model name..." onChange={setModelName} />
          {modelError !== "" && <p className="settings-error">{modelError}</p>}
          <Button type="submit" disabled={!canSubmitModel}>
            Submit
          </Button>
        </form>
      </Modal>
      <Modal open={modal === "credential"} label="Add a credential" title="Add a credential" size="narrow" onClose={() => setModal(null)}>
        <form className="settings-modal-form" onSubmit={(event) => void submitCredential(event)}>
          <ItemSelector
            items={providerOptions}
            selectedId={credentialProvider}
            onSelect={setCredentialProvider}
            hasMore={false}
            onLoadMore={() => {}}
            label="Provider"
            placeholder="Select a provider..."
          />
          <TextInput value={credentialName} label="Credential name" placeholder="Insert a name...." onChange={setCredentialName} />
          <TextInput value={credentialKey} label="Api Key" type="password" onChange={setCredentialKey} />
          {credentialError !== "" && <p className="settings-error">{credentialError}</p>}
          <Button type="submit" disabled={!canSubmitCredential}>
            Submit
          </Button>
        </form>
      </Modal>
    </section>
  )
}

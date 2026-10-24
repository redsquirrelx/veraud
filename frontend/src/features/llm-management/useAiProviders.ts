import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, createAiCredential, createAiModel, deleteAiCredential, deleteAiModel, listAiProviders, updateAiCredential, updateAiModel, type AiCredentialSummary, type AiModelSummary, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"

type ProviderLoadFailure = { key: ParseKeys<"settings"> } | { detail: string }

export function useAiProviders() {
  const { t } = useTranslation("settings")
  const [providers, setProviders] = useState<AiProviderDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailure, setLoadFailure] = useState<ProviderLoadFailure | null>(null)
  const mounted = useRef(true)
  const loadError = loadFailure === null ? "" : "detail" in loadFailure ? loadFailure.detail : t(loadFailure.key)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const load = useCallback(async (isCurrent: () => boolean, showLoading = true) => {
    if (showLoading) setLoading(true)
    try {
      const rows = await listAiProviders()
      if (!isCurrent()) return
      setProviders(rows)
      setLoadFailure(null)
    } catch (failure) {
      if (!isCurrent()) return
      setProviders([])
      setLoadFailure(failure instanceof ApiError && failure.messageSource !== "client"
        ? { detail: failure.message } : { key: "models.loadFailed" })
    } finally {
      if (isCurrent()) setLoading(false)
    }
  }, [])

  const refresh = useCallback(() => load(() => mounted.current), [load])

  useEffect(() => {
    let alive = true
    void Promise.resolve().then(() => load(() => alive, false))
    return () => {
      alive = false
    }
  }, [load])

  const addModel = useCallback(async (aiProviderId: number, name: string): Promise<AiModelSummary> => {
    const created = await createAiModel(aiProviderId, name)
    await refresh()
    return created
  }, [refresh])

  const editModel = useCallback(async (aiProviderId: number, modelId: number, name: string): Promise<AiModelSummary> => {
    const updated = await updateAiModel(aiProviderId, modelId, name)
    await refresh()
    return updated
  }, [refresh])

  const removeModel = useCallback(async (aiProviderId: number, modelId: number): Promise<void> => {
    await deleteAiModel(aiProviderId, modelId)
    await refresh()
  }, [refresh])

  const addCredential = useCallback(async (aiProviderId: number, name: string, apiKey: string): Promise<AiCredentialSummary> => {
    const created = await createAiCredential(aiProviderId, name, apiKey)
    await refresh()
    return created
  }, [refresh])

  const editCredential = useCallback(async (aiProviderId: number, credentialId: number, name: string, apiKey?: string): Promise<AiCredentialSummary> => {
    const updated = await updateAiCredential(aiProviderId, credentialId, name, apiKey)
    await refresh()
    return updated
  }, [refresh])

  const removeCredential = useCallback(async (aiProviderId: number, credentialId: number): Promise<void> => {
    await deleteAiCredential(aiProviderId, credentialId)
    await refresh()
  }, [refresh])

  return { providers, loading, loadError, refresh, addModel, editModel, removeModel, addCredential, editCredential, removeCredential }
}

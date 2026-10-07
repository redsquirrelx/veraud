import { useCallback, useEffect, useRef, useState } from "react"
import { ApiError, createAiCredential, createAiModel, deleteAiCredential, deleteAiModel, listAiProviders, type AiCredentialSummary, type AiModelSummary, type AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"

export function useAiProviders() {
  const [providers, setProviders] = useState<AiProviderDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async () => {    setLoading(true)
    try {
      const rows = await listAiProviders()
      if (!mounted.current) {
        return
      }
      setProviders(rows)
      setLoadError("")
    } catch (failure) {
      if (!mounted.current) {
        return
      }
      setProviders([])
      setLoadError(failure instanceof ApiError ? failure.message : "Could not load AI providers")
    } finally {
      if (mounted.current) {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    let alive = true
    listAiProviders().then(
      (rows) => {
        if (!alive) {
          return
        }
        setProviders(rows)
        setLoadError("")
        setLoading(false)
      },
      (failure: unknown) => {
        if (!alive) {
          return
        }
        setProviders([])
        setLoadError(failure instanceof ApiError ? failure.message : "Could not load AI providers")
        setLoading(false)
      }
    )
    return () => {
      alive = false
    }
  }, [])

  const addModel = useCallback(async (aiProviderId: number, name: string): Promise<AiModelSummary> => {
    const created = await createAiModel(aiProviderId, name)
    await refresh()
    return created
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

  const removeCredential = useCallback(async (aiProviderId: number, credentialId: number): Promise<void> => {
    await deleteAiCredential(aiProviderId, credentialId)
    await refresh()
  }, [refresh])

  return { providers, loading, loadError, refresh, addModel, removeModel, addCredential, removeCredential }
}

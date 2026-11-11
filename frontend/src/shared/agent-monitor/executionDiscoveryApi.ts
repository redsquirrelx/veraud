import { requestJson } from "../../infrastructure/http-client/httpClient.ts"

export async function discoverExecutions(signal?: AbortSignal): Promise<number[]> {
  const result = await requestJson<{ ids: unknown }>("/api/agent-executions/recent", "Could not discover executions", { signal }, false)
  return Array.isArray(result?.ids) ? result.ids.filter((id): id is number => Number.isInteger(id) && id > 0).slice(0, 50) : []
}

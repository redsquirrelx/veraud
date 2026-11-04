import { request as httpRequest } from "node:http"
import { request as httpsRequest } from "node:https"

/** Execution endpoints send headers only when the run finishes. Native fetch's
 * independent 300s headers timeout expires before our audit deadline. Use one
 * explicit end-to-end deadline, including reading the result body, instead. */
export function executionRequest(url: string, body: unknown, timeoutMs: number): Promise<Response> {
  const target = new URL(url)
  if (target.protocol !== "http:" && target.protocol !== "https:") throw new Error("Unsupported agent-server protocol")
  const payload = JSON.stringify(body)
  return new Promise((resolve, reject) => {
    const request = (target.protocol === "https:" ? httpsRequest : httpRequest)(target, {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": Buffer.byteLength(payload) },
      signal: AbortSignal.timeout(timeoutMs),
    }, (response) => {
      const chunks: Buffer[] = []
      response.on("data", (chunk: Buffer) => chunks.push(chunk))
      response.on("error", reject)
      response.on("end", () => {
        const status = response.statusCode ?? 502
        resolve(new Response([204, 205, 304].includes(status) ? null : Buffer.concat(chunks), { status }))
      })
    })
    request.on("error", reject)
    request.end(payload)
  })
}

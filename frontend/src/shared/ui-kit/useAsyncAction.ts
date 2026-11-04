import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"

interface AsyncOptions {
  timeoutMs?: number
}

export function useAsyncAction<Args extends unknown[]>(action: (...args: Args) => Promise<void>, options?: AsyncOptions) {
  const { t } = useTranslation("common")
  const timeoutMs = options?.timeoutMs
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState<{ key: ParseKeys<"common">, milliseconds?: number } | { detail: string } | null>(null)
  const error = failure === null ? null : "detail" in failure ? failure.detail : t(failure.key, { milliseconds: failure.milliseconds })
  const mounted = useRef(true)
  const busy = useRef(false)
  const token = useRef(0)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  async function run(...args: Args) {
    if (busy.current) {
      return
    }
    busy.current = true
    const id = ++token.current
    const alive = () => mounted.current && token.current === id
    setLoading(true)
    setFailure(null)

    let timer: ReturnType<typeof setTimeout> | null = null
    try {
      const work = action(...args)
      if (timeoutMs === undefined) {
        await work
      } else {
        await new Promise<void>((resolve, reject) => {
          timer = setTimeout(() => {
            token.current += 1
            busy.current = false
            if (mounted.current) {
              setLoading(false)
              setFailure({ key: "ui.asyncAction.timeout", milliseconds: timeoutMs })
            }
            reject(new Error("Timed out"))
          }, timeoutMs)
          work.then(resolve, reject)
        })
      }
    } catch (unknownError) {
      if (alive()) {
        setFailure(unknownError instanceof Error ? { detail: unknownError.message } : { key: "ui.asyncAction.failed" })
      }
    } finally {
      if (timer !== null) {
        clearTimeout(timer)
      }
      if (token.current === id) {
        busy.current = false
        if (mounted.current) {
          setLoading(false)
        }
      }
    }
  }

  return { loading, error, run }
}

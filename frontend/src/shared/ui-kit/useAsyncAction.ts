import { useEffect, useRef, useState } from "react"

interface AsyncOptions {
  timeoutMs?: number
}

export function useAsyncAction<Args extends unknown[]>(action: (...args: Args) => Promise<void>, options?: AsyncOptions) {
  const timeoutMs = options?.timeoutMs
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
    setError(null)

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
              setError(`Timed out after ${timeoutMs}ms`)
            }
            reject(new Error("Timed out"))
          }, timeoutMs)
          work.then(resolve, reject)
        })
      }
    } catch (unknownError) {
      if (alive()) {
        setError(unknownError instanceof Error ? unknownError.message : "Something went wrong")
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

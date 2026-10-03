import { useEffect, useRef, useState } from "react"
import { ApiError, registerProject, type RegisteredProject } from "../../infrastructure/http-client/httpClient.ts"

export type RegisterState = "idle" | "loading" | "success" | "error"

function isTimeout(error: unknown): boolean {
  const name = error instanceof Error || error instanceof DOMException ? error.name : ""
  return name === "AbortError" || name === "TimeoutError"
}

const SUBMIT_COOLDOWN_MS = 2000

export function useRegisterProject() {
  const [url, setUrl] = useState("")
  const [cooling, setCooling] = useState(false)
  const [state, setState] = useState<RegisterState>("idle")
  const [message, setMessage] = useState("")
  const [project, setProject] = useState<RegisteredProject | null>(null)
  const mounted = useRef(true)
  const pending = useRef(0)
  const coolingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (coolingTimer.current !== null) {
        clearTimeout(coolingTimer.current)
      }
    }
  }, [])

  function changeUrl(value: string) {
    setUrl(value)
    if (state === "success" || state === "error") {
      reset()
    }
  }

  async function register() {
    const trimmed = url.trim()
    if (trimmed === "" || cooling) {
      return
    }
    setUrl("")
    setCooling(true)
    coolingTimer.current = setTimeout(() => {
      if (mounted.current) {
        setCooling(false)
      }
    }, SUBMIT_COOLDOWN_MS)
    pending.current += 1
    setState("loading")
    setMessage("")
    setProject(null)
    try {
      const created = await registerProject(trimmed)
      if (!mounted.current) {
        return
      }
      setProject(created)
      setMessage(`Project ${created.repositoryOwner}/${created.repositoryName} registered`)
      setState("success")
    } catch (error) {
      if (!mounted.current) {
        return
      }
      setProject(null)
      if (error instanceof ApiError) {
        setMessage(error.message)
      } else if (isTimeout(error)) {
        setMessage("The request took too long and was cancelled")
      } else if (error instanceof TypeError) {
        setMessage("Could not connect to the backend")
      } else {
        console.log(error)
        setMessage("Unexpected error")
      }
      setState("error")
    } finally {
      pending.current -= 1
      if (pending.current > 0 && mounted.current) {
        setState("loading")
      }
    }
  }

  function reset() {
    setState("idle")
    setMessage("")
    setProject(null)
  }

  return { url, changeUrl, cooling, state, message, project, register, reset }
}

import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, registerProject, type RegisteredProject } from "../../infrastructure/http-client/httpClient.ts"

export type RegisterState = "idle" | "loading" | "success" | "error"
type RegistrationMessage = { key: ParseKeys<"projects">, name?: string } | { detail: string } | null

function isTimeout(error: unknown): boolean {
  const name = error instanceof Error || error instanceof DOMException ? error.name : ""
  return name === "AbortError" || name === "TimeoutError"
}

const SUBMIT_COOLDOWN_MS = 2000

export function useRegisterProject(options?: { onRegistered?: () => void; shallowClone?: boolean }) {
  const { t } = useTranslation("projects")
  const [url, setUrl] = useState("")
  const [cooling, setCooling] = useState(false)
  const [state, setState] = useState<RegisterState>("idle")
  const [messageState, setMessageState] = useState<RegistrationMessage>(null)
  const [project, setProject] = useState<RegisteredProject | null>(null)
  const mounted = useRef(true)
  const pending = useRef(0)
  const coolingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const message = messageState === null ? "" : "detail" in messageState ? messageState.detail
    : t(messageState.key, messageState.name === undefined ? {} : { name: messageState.name })

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
    const shallowClone = options?.shallowClone ?? false
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
    setMessageState(null)
    setProject(null)
    try {
      const created = await registerProject(trimmed, shallowClone)
      if (!mounted.current) {
        return
      }
      setProject(created)
      setMessageState({ key: "registration.registered", name: `${created.repositoryOwner}/${created.repositoryName}` })
      setState("success")
      options?.onRegistered?.()
    } catch (error) {
      if (!mounted.current) {
        return
      }
      setProject(null)
      if (error instanceof ApiError) {
        setMessageState(error.messageSource === "client" ? { key: "registration.errors.unexpected" } : { detail: error.message })
      } else if (isTimeout(error)) {
        setMessageState({ key: "registration.errors.timeout" })
      } else if (error instanceof TypeError) {
        setMessageState({ key: "registration.errors.network" })
      } else {
        console.log(error)
        setMessageState({ key: "registration.errors.unexpected" })
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
    setMessageState(null)
    setProject(null)
  }

  return { url, changeUrl, cooling, state, message, project, register, reset }
}

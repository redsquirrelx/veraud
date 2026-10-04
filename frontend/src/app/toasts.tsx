import { useCallback, useRef, useState, type ReactNode } from "react"
import { ToastsContext } from "./use-toasts.ts"

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Array<{ id: number, kind: "success" | "error", message: string }>>([])
  const nextId = useRef(1)

  const pushToast = useCallback((kind: "success" | "error", message: string) => {
    const id = nextId.current
    nextId.current += 1
    setToasts((current) => [...current, { id, kind, message }])
  }, [])

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  return (
    <ToastsContext.Provider value={{ toasts, pushToast, dismissToast }}>
      {children}
    </ToastsContext.Provider>
  )
}

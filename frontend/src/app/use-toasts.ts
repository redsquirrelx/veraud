import { createContext, useContext } from "react"

export interface ToastItem {
  id: number
  kind: "success" | "error"
  message: string
}

export interface ToastsContextValue {
  toasts: ToastItem[]
  pushToast: (kind: "success" | "error", message: string) => void
  dismissToast: (id: number) => void
}

export const ToastsContext = createContext<ToastsContextValue | null>(null)

export function useToasts(): ToastsContextValue {
  const context = useContext(ToastsContext)
  if (context === null) {
    throw new Error("useToasts must be used inside ToastProvider")
  }
  return context
}

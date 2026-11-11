import { createContext, useContext, useState, type ReactNode } from "react"
import { SettingsModal } from "./SettingsModal.tsx"
import type { SettingsTab } from "../pages/settings/SettingsPage.tsx"

export interface SettingsContextValue {
  /** Open the shared settings modal; pass a tab to force it, otherwise the saved (or default) tab is used. */
  openSettings: (tab?: SettingsTab) => void
}

export const SettingsContext = createContext<SettingsContextValue>({ openSettings: () => {} })

/** App-wide handle for opening the shared settings modal. */
export function useSettings() {
  return useContext(SettingsContext)
}

/** Owns the single app-wide settings modal and exposes openSettings to the tree. */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [initialTab, setInitialTab] = useState<SettingsTab | undefined>(undefined)

  function openSettings(tab?: SettingsTab) {
    setInitialTab(tab)
    setOpen(true)
  }

  function close() {
    setOpen(false)
    // Drop the forced tab so a later open falls back to the saved preference.
    setInitialTab(undefined)
  }

  return <SettingsContext.Provider value={{ openSettings }}>
    {children}
    <SettingsModal open={open} initialTab={initialTab} onClose={close} />
  </SettingsContext.Provider>
}

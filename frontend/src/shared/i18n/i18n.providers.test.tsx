import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { useTranslation } from "react-i18next"
import { AppProviders } from "../../app/providers.tsx"
import { changeLanguage, initializeI18n } from "./index.ts"

class FakeSocket {
  addEventListener() {}
  close() {}
}

function SettingsTitle() {
  const { t } = useTranslation("settings")
  return <h1>{t("title")}</h1>
}

beforeAll(async () => {
  await initializeI18n("en")
})

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeSocket)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("AppProviders i18n wiring", () => {
  it("exposes translations and reacts to language changes", async () => {
    await changeLanguage("es")
    render(
      <AppProviders>
        <SettingsTitle />
      </AppProviders>
    )
    expect(screen.getByRole("heading")).toHaveTextContent("Configuración")

    await changeLanguage("en")
    expect(screen.getByRole("heading")).toHaveTextContent("Settings")
  })
})

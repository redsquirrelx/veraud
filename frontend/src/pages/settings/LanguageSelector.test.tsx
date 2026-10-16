import { useState } from "react"
import { beforeAll, beforeEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { I18nextProvider } from "react-i18next"
import { i18n, initializeI18n } from "../../shared/i18n/index.ts"
import { languageStorageKey, setStoredLanguage } from "../../shared/i18n/language.ts"
import { LanguageSelector } from "./LanguageSelector.tsx"

function renderSelector() {
  render(
    <I18nextProvider i18n={i18n}>
      <LanguageSelector />
    </I18nextProvider>
  )
}

function Harness() {
  const [pinned, setPinned] = useState(false)
  return (
    <div>
      <LanguageSelector />
      <label>
        <input type="checkbox" checked={pinned} onChange={(event) => setPinned(event.target.checked)} />
        Keep me
      </label>
    </div>
  )
}

function renderHarness() {
  render(
    <I18nextProvider i18n={i18n}>
      <Harness />
    </I18nextProvider>
  )
}

beforeAll(async () => {
  await initializeI18n("en")
})

beforeEach(async () => {
  window.localStorage.clear()
  document.documentElement.lang = "en"
  await initializeI18n("en")
})

describe("LanguageSelector", () => {
  it("marks the current language", () => {
    renderSelector()

    expect(screen.getByRole("radio", { name: "English" })).toBeChecked()
    expect(screen.getByRole("radio", { name: "Español" })).not.toBeChecked()
  })

  it("reflects a stored preference on initialize", async () => {
    setStoredLanguage("es")
    await initializeI18n()
    renderSelector()

    expect(screen.getByText("Idioma")).toBeDefined()
    expect(screen.getByRole("radio", { name: "Español" })).toBeChecked()
  })

  it("applies the change immediately, persists it and keeps sibling state", async () => {
    const user = userEvent.setup()
    renderHarness()

    await user.click(screen.getByRole("checkbox", { name: "Keep me" }))
    expect(screen.getByRole("checkbox", { name: "Keep me" })).toBeChecked()

    await user.click(screen.getByRole("radio", { name: "Español" }))

    expect(screen.getByText("Idioma")).toBeDefined()
    expect(screen.getByRole("radio", { name: "Español" })).toBeChecked()
    expect(JSON.parse(window.localStorage.getItem(languageStorageKey)!)).toBe("es")
    expect(document.documentElement.lang).toBe("es")
    expect(screen.getByRole("checkbox", { name: "Keep me" })).toBeChecked()

    // A fresh initialization (reload) keeps the stored choice.
    await initializeI18n()
    expect(screen.getByRole("radio", { name: "Español" })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "Keep me" })).toBeChecked()
  })
})

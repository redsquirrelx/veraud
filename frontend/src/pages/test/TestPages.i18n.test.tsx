import { beforeEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage, initializeI18n } from "../../shared/i18n/index.ts"
import { TestIndexPage } from "./TestIndexPage.tsx"
import { TestDropdownPage } from "../test-dropdown/TestDropdownPage.tsx"

beforeEach(async () => {
  await initializeI18n("en")
})

describe("test pages", () => {
  it("translates the index and keeps playground links", async () => {
    render(<MemoryRouter><TestIndexPage /></MemoryRouter>)
    expect(screen.getByRole("heading", { name: "Test playgrounds" })).toBeDefined()

    await changeLanguage("es")

    expect(screen.getByRole("heading", { name: "Zona de pruebas" })).toBeDefined()
    expect(screen.getByRole("link", { name: /Muestra de etapas/ })).toHaveAttribute("href", "/test/stage-showcase")
  })

  it("translates dropdown chrome", async () => {
    render(<MemoryRouter><TestDropdownPage /></MemoryRouter>)

    await changeLanguage("es")

    expect(screen.getByRole("heading", { name: "Zona de desplegables" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Analizar" })).toBeDefined()
  })
})

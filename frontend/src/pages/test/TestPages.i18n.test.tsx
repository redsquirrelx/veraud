import { beforeEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { changeLanguage, initializeI18n } from "../../shared/i18n/index.ts"
import { TestIndexPage } from "./TestIndexPage.tsx"
import { TestDropdownPage } from "../test-dropdown/TestDropdownPage.tsx"
import { ComponentTestPage } from "./ComponentTestPage.tsx"
import { TestControlsPage } from "../test-controls/TestControlsPage.tsx"
import { TestFileViewerPage } from "../test-file-viewer/TestFileViewerPage.tsx"
import userEvent from "@testing-library/user-event"

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

  it("translates showcase copy, plural counts, and annotations but keeps sample content", async () => {
    render(<MemoryRouter><>
      <ComponentTestPage />
      <TestControlsPage />
      <TestFileViewerPage />
    </></MemoryRouter>)

    await changeLanguage("es")

    expect(screen.getByText("Proyectos y repositorios")).toBeInTheDocument()
    expect(screen.getByText("Supervisión autónoma continua de atributos de calidad según ISO/IEC 25010.")).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole("button", { name: "OpenAI" })[0]!)
    expect(screen.getAllByText("3 modelos")).toHaveLength(3)
    await userEvent.click(screen.getByRole("button", { name: "Docs de API" }))
    expect(screen.getByText("API HTTP · Swagger")).toBeInTheDocument()
    expect(screen.getByText("Importe sin validar")).toBeInTheDocument()
    expect(screen.getByText("export function settle(payment: Settlement): Settlement {", { exact: false })).toBeInTheDocument()
  })
})

import { afterEach, describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TaskMenu } from "./TaskMenu.tsx"
import { TASK_KIND_OPTIONS } from "./taskVisibility.ts"
import { changeLanguage, i18n } from "../i18n/index.ts"
import { languageStorageKey } from "../i18n/language.ts"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"

const running: ActiveTask = {
  id: 1,
  projectId: 2,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  description: "cloning acme/Demo",
  command: "git clone --depth 1 https://github.com/acme/Demo.git /workspace/Demo",
  status: "Running",
  kind: "clone",
  exitCode: null,
}

const queued: ActiveTask = {
  id: 2,
  projectId: 3,
  repositoryOwner: "acme",
  repositoryName: "Other",
  description: "cloning acme/Other",
  status: "Queued",
  kind: "clone",
  exitCode: null,
}

describe("TaskMenu", () => {
  it("opens a task with the keyboard and keeps it open after status updates", async () => {
    const { rerender } = render(<TaskMenu tasks={[running]} />)
    const toggle = screen.getByRole("button", { name: "Show command for cloning acme/Demo" })
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    toggle.focus()
    await userEvent.keyboard("{Enter}")
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText(running.command!)).toBeVisible()
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toHaveAttribute("aria-hidden", "false")
    rerender(<TaskMenu tasks={[{ ...running, status: "Succeded" }]} />)
    expect(screen.getByRole("button", { name: "Hide command for cloning acme/Demo" })).toHaveAttribute("aria-expanded", "true")
    await userEvent.click(screen.getByText(running.command!))
    expect(screen.getByRole("button", { name: "Hide command for cloning acme/Demo" })).toHaveAttribute("aria-expanded", "true")
    await userEvent.click(screen.getByRole("button", { name: "Hide command for cloning acme/Demo" }))
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toHaveAttribute("aria-hidden", "true")
  })

  it("expands tasks independently and preserves them when toggling the whole menu", async () => {
    render(<TaskMenu tasks={[queued, running]} />)
    await userEvent.click(screen.getByRole("button", { name: "Expand tasks" }))
    await userEvent.click(screen.getByRole("button", { name: "Show command for cloning acme/Demo" }))
    await userEvent.click(screen.getByRole("button", { name: "Show command for cloning acme/Other" }))
    expect(screen.getByText("Command unavailable")).toBeVisible()
    await userEvent.click(screen.getByRole("button", { name: "Hide command for cloning acme/Other" }))
    expect(screen.getByRole("button", { name: "Hide command for cloning acme/Demo" })).toHaveAttribute("aria-expanded", "true")
    await userEvent.click(screen.getByRole("button", { name: "Collapse tasks" }))
    await userEvent.click(screen.getByRole("button", { name: "Expand tasks" }))
    expect(screen.getByRole("button", { name: "Hide command for cloning acme/Demo" })).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByRole("button", { name: "Show command for cloning acme/Other" })).toHaveAttribute("aria-expanded", "false")
  })
  it("renders nothing before any task", () => {
    const { container } = render(<TaskMenu tasks={[]} />)

    expect(container.innerHTML).toBe("")
  })

  it("keeps finished tasks with their final status", async () => {
    const { rerender } = render(<TaskMenu tasks={[running]} />)

    expect(screen.getByText("cloning acme/Demo")).toBeDefined()

    rerender(
      <TaskMenu
        tasks={[{ ...running, status: "Succeded", exitCode: 0 }]}
      />
    )

    expect(screen.getByText("cloning acme/Demo")).toBeDefined()
    expect(screen.getByText("Succeded")).toBeDefined()
    expect(screen.getByLabelText("Done")).toBeDefined()
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull()
  })

  it("collapsed shows only the running task", () => {
    render(<TaskMenu tasks={[queued, running]} />)

    expect(screen.getByText("cloning acme/Demo")).toBeDefined()
    expect(screen.queryByText("cloning acme/Other")).toBeNull()
  })

  it("collapsed shows the last task when all are done", () => {
    render(
      <TaskMenu
        tasks={[
          { ...running, status: "Succeded", exitCode: 0 },
          { ...queued, status: "Failed", exitCode: 1 },
        ]}
      />
    )

    expect(screen.getByText("cloning acme/Other")).toBeDefined()
    expect(screen.queryByText("cloning acme/Demo")).toBeNull()
  })

  it("expanded shows newest first", async () => {
    const { container } = render(<TaskMenu tasks={[queued, running]} />)

    await userEvent.click(screen.getByRole("button", { name: "Expand tasks" }))

    const cards = container.querySelectorAll(".task-menu-list .ui-card")
    expect(cards.length).toBe(2)
    expect(cards[0]?.textContent).toContain("cloning acme/Demo")
    expect(cards[1]?.textContent).toContain("cloning acme/Other")
  })

  it("closes through its X button and reopens on new tasks", async () => {
    const { rerender } = render(<TaskMenu tasks={[running]} />)

    await userEvent.click(screen.getByRole("button", { name: "Close task menu" }))

    await waitFor(() => {
      expect(screen.queryByText("cloning acme/Demo")).toBeNull()
    })

    rerender(<TaskMenu tasks={[running, queued]} />)

    expect(screen.getByText("cloning acme/Demo")).toBeDefined()
  })
})

describe("TaskMenu Spanish", () => {
  afterEach(async () => {
    await changeLanguage("en")
  })

  it("translates menu chrome and keeps language state consistent", async () => {
    await changeLanguage("es")

    expect(document.documentElement.lang).toBe("es")
    expect(window.localStorage.getItem(languageStorageKey)).toBe(JSON.stringify("es"))

    render(<TaskMenu tasks={[queued, running]} />)

    expect(screen.getByRole("status", { name: "Tareas activas" })).toBeDefined()
    expect(screen.getByText("Tareas activas (2)")).toBeDefined()
    expect(screen.getByRole("button", { name: "Expandir tareas" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Cerrar el menú de tareas" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Mostrar el comando de cloning acme/Demo" })).toBeDefined()
    // Backend content stays untranslated while chrome translates.
    expect(screen.getByText("cloning acme/Demo")).toBeDefined()
    expect(screen.getByText("En ejecución")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Expandir tareas" }))

    expect(screen.getByRole("button", { name: "Contraer tareas" })).toBeDefined()
    expect(screen.getByText("Comando no disponible")).toBeDefined()
    expect(screen.getByRole("button", { name: "Mostrar el comando de cloning acme/Other" })).toBeDefined()
  })

  it("resolves every task-kind option through its label and hint keys", () => {
    const en = i18n.getFixedT("en", "tasks")
    const es = i18n.getFixedT("es", "tasks")

    for (const option of TASK_KIND_OPTIONS) {
      expect(en(option.labelKey)).not.toBe(option.labelKey)
      expect(en(option.hintKey)).not.toBe(option.hintKey)
      expect(es(option.labelKey)).not.toBe(option.labelKey)
      expect(es(option.hintKey)).not.toBe(option.hintKey)
    }
    expect(es("kindOptions.clone.label")).toBe("Clonar")
    expect(es("kindOptions.clone.hint")).toBe("Descarga inicial del repositorio")
    expect(en("kindOptions.clone.label")).toBe("Clone")
  })
})

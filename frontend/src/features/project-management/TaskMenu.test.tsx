import { describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { TaskMenu } from "./TaskMenu.tsx"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"

const running: ActiveTask = {
  id: 1,
  projectId: 2,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  description: "cloning acme/Demo",
  status: "Running",
  exitCode: null,
}

const queued: ActiveTask = {
  id: 2,
  projectId: 3,
  repositoryOwner: "acme",
  repositoryName: "Other",
  description: "cloning acme/Other",
  status: "Queued",
  exitCode: null,
}

describe("TaskMenu", () => {
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

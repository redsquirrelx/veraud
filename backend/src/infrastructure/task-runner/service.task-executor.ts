import type { ServiceTaskCommand, TaskContext, TaskExecutor, TaskOutput, TaskScheduling } from "./task.types.js"

export interface ServiceTaskHandler extends TaskScheduling {
  run(input: unknown, context: TaskContext): Promise<TaskOutput | void>
}

/** Explicit allowlist: no dynamic imports, arbitrary URLs or shell commands. */
export function serviceTaskExecutor(handlers: Readonly<Record<string, ServiceTaskHandler>>): TaskExecutor {
  const registry = new Map(Object.entries(handlers))
  return {
    prepare(command, context) {
      if (command.kind !== "service") return
      const handler = registry.get(command.name)
      if (!handler) throw new Error("Unknown service task")
      const { run, ...scheduling } = handler
      return {
        ...scheduling,
        command: null,
        // Unlike Git diagnostics, arbitrary service errors may contain credentials.
        failureMessage: "Service task failed",
        run: () => run.call(handler, command.input, context),
      }
    },
  }
}

export function serviceTask(name: string, input?: unknown): ServiceTaskCommand {
  return { kind: "service", name, input }
}

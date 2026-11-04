import { describeGitCommand, executeGit, formatCommand, gitExecutionOptions, isGitCommand } from "./git.executor.js"
import type { TaskExecutor } from "./task.types.js"

/** All CLI details and Git scheduling policy stay outside the generic runner. */
export function gitTaskExecutor(workspaceDir: string, execute: typeof executeGit = executeGit): TaskExecutor {
  return {
    prepare(command) {
      if (!isGitCommand(command)) return
      const description = describeGitCommand(command, workspaceDir)
      const initializesProject = command.kind === "clone"
      const exclusive = initializesProject || ["pull", "fetch", "checkout-branch", "checkout-detach"].includes(command.kind)
      return {
        command: formatCommand(description.binary, description.argv),
        projectAccess: exclusive ? "exclusive" : "shared",
        initializesProject,
        ...(initializesProject ? { serialGroup: "git.clone", initializationLabel: "clone" } : {}),
        updatesProjectStatus: description.mutating,
        failureExitCode: 1,
        async run() {
          const { stdout, stderr } = await execute(description.binary, description.argv, gitExecutionOptions(command))
          return { exitCode: 0, logTrail: `${stdout}\n${stderr}`, output: stdout }
        },
      }
    },
  }
}

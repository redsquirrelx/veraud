import { join } from "node:path"

export type GitCommand =
  | { kind: "clone", cloneUrl: string, folder: string }
  | { kind: "pull", folder: string }
  | { kind: "fetch", folder: string }
  | { kind: "list-branches", folder: string }
  | { kind: "rev-parse", folder: string, branch: string }
  | { kind: "checkout-detach", folder: string, commitHash: string }
  | { kind: "checkout-branch", folder: string, branch: string }
  | { kind: "log-commits", folder: string, branch: string, limit: number, offset: number }

const GIT_KINDS: ReadonlySet<string> = new Set([
  "clone",
  "pull",
  "fetch",
  "list-branches",
  "rev-parse",
  "checkout-detach",
  "checkout-branch",
  "log-commits",
])

export function isGitCommand(command: { kind: string }): command is GitCommand {
  return GIT_KINDS.has(command.kind)
}

export function gitArgv(command: GitCommand, targetDir: string): string[] {
  if (command.kind === "clone") {
    return ["clone", command.cloneUrl, targetDir]
  }

  if (command.kind === "pull") {
    return ["-C", targetDir, "pull"]
  }

  if (command.kind === "fetch") {
    return ["-C", targetDir, "fetch"]
  }

  if (command.kind === "list-branches") {
    return ["-C", targetDir, "branch", "-a"]
  }

  if (command.kind === "rev-parse") {
    return ["-C", targetDir, "rev-parse", command.branch]
  }

  if (command.kind === "checkout-detach") {
    return ["-C", targetDir, "checkout", "--force", "--detach", command.commitHash]
  }

  if (command.kind === "checkout-branch") {
    return ["-C", targetDir, "checkout", "--force", command.branch]
  }

  return [
    "-C",
    targetDir,
    "log",
    "--format=%H%x09%s",
    `--max-count=${command.limit}`,
    `--skip=${command.offset}`,
    command.branch,
  ]
}

export function touchesProjectStatus(command: GitCommand): boolean {
  if (command.kind === "clone") {
    return true
  }

  if (command.kind === "pull") {
    return true
  }

  if (command.kind === "fetch") {
    return true
  }

  return false
}

export function describeGitCommand(
  command: GitCommand,
  workspaceDir: string
): { binary: string, argv: string[], mutating: boolean } {
  return {
    binary: "git",
    argv: gitArgv(command, join(workspaceDir, command.folder)),
    mutating: touchesProjectStatus(command),
  }
}

import { spawn, type ChildProcess } from "node:child_process"
import { join } from "node:path"

export const REMOTE_GIT_TIMEOUT_MS = 5 * 60 * 1000
const MAX_OUTPUT_BYTES = 1024 * 1024

export interface GitExecutionOptions {
  remote: boolean
  timeoutMs?: number
}

export function gitExecutionOptions(command: GitCommand): GitExecutionOptions {
  const remote = command.kind === "clone" || command.kind === "pull" || command.kind === "fetch"
  return remote ? { remote: true, timeoutMs: REMOTE_GIT_TIMEOUT_MS } : { remote: false }
}

export function gitEnvironment(remote: boolean, base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  if (!remote) return base

  const existingSshCommand = base.GIT_SSH_COMMAND?.trim() || "ssh"
  const sshOptions = [
    "-o BatchMode=yes",
    "-o NumberOfPasswordPrompts=0",
    "-o ConnectTimeout=15",
    "-o ConnectionAttempts=1",
    "-o StrictHostKeyChecking=yes",
  ].join(" ")

  return {
    ...base,
    GIT_TERMINAL_PROMPT: "0",
    GCM_INTERACTIVE: "Never",
    // Preserve an externally configured SSH wrapper/identity options and append
    // non-interactive OpenSSH settings. SSH still reads its normal config,
    // known_hosts and inherited SSH_AUTH_SOCK.
    GIT_SSH_COMMAND: `${existingSshCommand} ${sshOptions}`,
  }
}

function terminateProcessTree(child: ChildProcess): Promise<void> {
  const pid = child.pid
  if (pid === undefined) return Promise.resolve()

  if (process.platform === "win32") {
    return new Promise((resolve) => {
      const taskkill = spawn("taskkill.exe", ["/PID", String(pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      })
      taskkill.once("error", () => {
        child.kill("SIGKILL")
        resolve()
      })
      taskkill.once("close", () => {
        if (child.exitCode === null) child.kill("SIGKILL")
        resolve()
      })
    })
  }

  try {
    process.kill(-pid, "SIGTERM")
  } catch {
    child.kill("SIGTERM")
  }
  return new Promise((resolve) => {
    const forceKill = setTimeout(() => {
      try {
        process.kill(-pid, "SIGKILL")
      } catch {
        child.kill("SIGKILL")
      }
    }, 2000)
    child.once("close", () => {
      clearTimeout(forceKill)
      resolve()
    })
  })
}

function outputText(stdout: string, stderr: string): string {
  return stderr.trim() || stdout.trim()
}

/** Execute Git without a shell, with non-interactive transport and a deadline for remote operations. */
export function executeGit(
  binary: string,
  argv: string[],
  options: GitExecutionOptions = { remote: false },
): Promise<{ stdout: string, stderr: string }> {
  return new Promise((resolve, reject) => {
    const remote = options.remote
    const timeoutMs = remote ? options.timeoutMs ?? REMOTE_GIT_TIMEOUT_MS : undefined
    const child = spawn(binary, argv, {
      env: gitEnvironment(remote),
      shell: false,
      windowsHide: true,
      detached: remote && process.platform !== "win32",
      stdio: ["ignore", "pipe", "pipe"],
    })
    let stdout = ""
    let stderr = ""
    let stdoutBytes = 0
    let stderrBytes = 0
    let failure: Error | null = null
    let timedOut = false
    let settled = false
    const timeout = timeoutMs === undefined ? undefined : setTimeout(() => {
      timedOut = true
      void terminateProcessTree(child)
    }, timeoutMs)

    function settleError(error: Error): void {
      if (settled) return
      settled = true
      if (timeout !== undefined) clearTimeout(timeout)
      reject(error)
    }

    function collect(stream: "stdout" | "stderr", chunk: Buffer): void {
      if (settled || failure !== null) return
      const chunkText = chunk.toString("utf8")
      if (stream === "stdout") {
        stdoutBytes += chunk.length
        if (stdoutBytes > MAX_OUTPUT_BYTES) failure = new Error("stdout maxBuffer length exceeded")
        else stdout += chunkText
      } else {
        stderrBytes += chunk.length
        if (stderrBytes > MAX_OUTPUT_BYTES) failure = new Error("stderr maxBuffer length exceeded")
        else stderr += chunkText
      }
      if (failure !== null) void terminateProcessTree(child)
    }

    child.stdout.on("data", (chunk: Buffer) => collect("stdout", chunk))
    child.stderr.on("data", (chunk: Buffer) => collect("stderr", chunk))
    child.once("error", (error) => settleError(error))
    child.once("close", (code, signal) => {
      if (settled) return
      settled = true
      if (timeout !== undefined) clearTimeout(timeout)
      if (timedOut) {
        const detail = outputText(stdout, stderr)
        reject(new Error(`Git command timed out after ${timeoutMs}ms${detail ? `: ${detail}` : ""}`))
      } else if (failure !== null) {
        reject(failure)
      } else if (code !== 0) {
        const detail = outputText(stdout, stderr)
        reject(new Error(detail || `Git command exited with ${signal ?? `code ${code}`}`))
      } else {
        resolve({ stdout, stderr })
      }
    })
  })
}

export type GitCommand =
  | { kind: "clone", cloneUrl: string, folder: string, shallowClone?: boolean }
  | { kind: "pull", folder: string }
  | { kind: "fetch", folder: string }
  | { kind: "list-branches", folder: string }
  | { kind: "list-tree", folder: string }
  | { kind: "rev-parse", folder: string, branch: string }
  | { kind: "checkout-detach", folder: string, commitHash: string }
  | { kind: "checkout-branch", folder: string, branch: string }
  | { kind: "log-commits", folder: string, branch: string, limit: number, offset: number }

const GIT_KINDS: ReadonlySet<string> = new Set([
  "clone",
  "pull",
  "fetch",
  "list-branches",
  "list-tree",
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
    return ["clone", ...(command.shallowClone === true ? ["--depth", "1"] : []), command.cloneUrl, targetDir]
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

  if (command.kind === "list-tree") {
    return ["-C", targetDir, "ls-tree", "-r", "--name-only", "HEAD"]
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

/** A readable representation of execFile arguments, not a shell script. */
export function formatCommand(binary: string, argv: string[]): string {
  return [binary, ...argv].map((argument) => {
    if (argument !== "" && /^[a-zA-Z0-9_./:@=,+%-]+$/.test(argument)) return argument
    return JSON.stringify(argument)
  }).join(" ")
}

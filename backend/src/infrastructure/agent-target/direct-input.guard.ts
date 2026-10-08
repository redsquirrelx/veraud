import { existsSync, readdirSync, statSync } from "node:fs"
import { isAbsolute, relative, resolve, sep } from "node:path"
import type { AgentInput } from "../agent-server-client/agent-server.client.js"
import { WorkspaceMissingError } from "./agent-target.resolver.js"

export class InvalidDirectInputError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "InvalidDirectInputError"
  }
}

/**
 * Resolves a direct-run input against the workspace without touching the DB.
 *
 * Passthrough by design: the backend does not know each agent's schema, so an
 * input without a `root_path` string is returned untouched (e.g. dummy's
 * `{code}`). When `root_path` is present it must resolve inside `workspaceDir`.
 *
 * Only the traversal check throws here so the controller can reject it
 * synchronously (422, no row created). Checkout existence is checked later in
 * the background dispatch so a missing folder becomes a Failed row, exactly
 * like the evaluation-backed path.
 */
export function sanitizeDirectInput(input: AgentInput, workspaceDir: string): AgentInput {
  if (input === null || typeof input !== "object" || Array.isArray(input)) {
    throw new InvalidDirectInputError("input must be an object")
  }

  const rootPath = (input as Record<string, unknown>)["root_path"]

  if (rootPath === undefined) {
    return input
  }

  if (typeof rootPath !== "string") {
    throw new InvalidDirectInputError("input.root_path must be a string")
  }

  const normalized = rootPath.replace(/\\/g, "/").trim()

  if (normalized === "") {
    throw new InvalidDirectInputError("input.root_path must not be empty")
  }

  if (normalized.includes("\0")) {
    throw new InvalidDirectInputError("input.root_path must not contain null bytes")
  }

  const root = resolve(workspaceDir)
  const resolved = isAbsolute(normalized) ? resolve(normalized) : resolve(root, normalized)

  if (!isInside(resolved, root)) {
    throw new InvalidDirectInputError("input.root_path must stay inside the workspace")
  }

  return { ...input, root_path: resolved }
}

/** Fails when a direct-run input points at a folder with nothing to analyze. */
export function assertDirectCheckout(input: AgentInput): void {
  const rootPath = (input as Record<string, unknown>)["root_path"]

  if (typeof rootPath !== "string") {
    return
  }

  try {
    if (statSync(rootPath).isFile()) {
      return
    }
  } catch {
    throw new WorkspaceMissingError(`No local checkout at ${rootPath}`)
  }

  if (existsSync(rootPath) === false || readdirSync(rootPath).length === 0) {
    throw new WorkspaceMissingError(`No local checkout at ${rootPath}`)
  }
}

function isInside(candidate: string, root: string): boolean {
  // Windows paths are case-insensitive, so compare lowered there.
  const sameCase = process.platform === "win32"
  const lowerCandidate = sameCase ? candidate.toLowerCase() : candidate
  const lowerRoot = sameCase ? root.toLowerCase() : root

  if (lowerCandidate === lowerRoot) {
    return false
  }

  const rel = relative(root, candidate)

  if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) {
    return false
  }

  // Belt and braces against `C:\ws-evil` sharing a string prefix with `C:\ws`.
  return lowerCandidate.startsWith(lowerRoot + sep)
}

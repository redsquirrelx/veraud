import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"

/** Walks up from `startDir` to the repository root (the first ancestor
 *  containing `.git`), so checkouts resolve identically no matter which
 *  nested package computes them. Returns null outside a git checkout. */
export function findRepoRoot(startDir: string): string | null {
  let current = resolve(startDir)
  for (;;) {
    if (existsSync(join(current, ".git"))) {
      return current
    }
    const parent = dirname(current)
    if (parent === current) {
      return null
    }
    current = parent
  }
}

/** Shared checkout root default: `<repo>/appdata/workspace`. Falls back to
 *  the historical layout when no git marker is found (e.g. exported zips). */
export function defaultWorkspaceDir(fromDir: string): string {
  const root = findRepoRoot(fromDir)
  if (root !== null) {
    return join(root, "appdata", "workspace")
  }
  return join(resolve(fromDir, ".."), "appdata", "workspace")
}

/** Explicit override wins; otherwise the shared repo-anchored default. */
export function resolveWorkspaceDir(fromDir: string, override: string): string {
  return override !== "" ? override : defaultWorkspaceDir(fromDir)
}

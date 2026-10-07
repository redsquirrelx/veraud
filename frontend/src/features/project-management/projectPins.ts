import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"

const STORAGE_KEY = "projects.pinned"

export function loadPinnedProjects(): number[] {
  const stored = localStorage.get<unknown>(STORAGE_KEY, [])

  if (!Array.isArray(stored)) {
    return []
  }

  return stored.filter((id): id is number => typeof id === "number" && Number.isInteger(id))
}

export function savePinnedProjects(ids: number[]): void {
  localStorage.set(STORAGE_KEY, ids)
}

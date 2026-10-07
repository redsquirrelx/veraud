import { useCallback, useEffect, useState } from "react"
import { listProjects, type ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import { loadPinnedProjects, savePinnedProjects } from "./projectPins.ts"

export type ProjectStatusFilter = "ALL" | "QUEUED" | "READY" | "SYNCING"
export type ProjectSortMode = "title" | "date"

export const PROJECT_PAGE_SIZE = 10

export function useProjects() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<ProjectStatusFilter>("ALL")
  const [sortMode, setSortMode] = useState<ProjectSortMode>("title")
  const [azDirection, setAzDirection] = useState<"asc" | "desc">("asc")
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [pinned, setPinned] = useState<number[]>(loadPinnedProjects)

  useEffect(() => {
    savePinnedProjects(pinned)
  }, [pinned])

  const prunePins = useCallback((rows: ProjectSummary[]) => {
    setPinned((current) => current.filter((id) => rows.some((project) => project.id === id)))
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const rows = await listProjects()
      setProjects(rows)
      prunePins(rows)
      setLoadError(false)
    } catch {
      setProjects([])
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [prunePins])

  useEffect(() => {
    let alive = true
    listProjects().then(
      (rows) => {
        if (alive) {
          setProjects(rows)
          prunePins(rows)
          setLoading(false)
        }
      },
      () => {
        if (alive) {
          setProjects([])
          setLoading(false)
          setLoadError(true)
        }
      }
    )
    return () => {
      alive = false
    }
  }, [prunePins])

  const filtered = projects.filter((project) => {
    const matchesText = `${project.repositoryOwner}/${project.repositoryName}`
      .toLowerCase()
      .includes(search.trim().toLowerCase())
    const matchesStatus = status === "ALL" || project.status === status
    return matchesText && matchesStatus
  })

  const sorted = [...filtered].sort((left, right) => {
    const leftPinned = pinned.includes(left.id)
    const rightPinned = pinned.includes(right.id)
    if (leftPinned !== rightPinned) {
      return leftPinned ? -1 : 1
    }
    const leftKey = sortMode === "title"
      ? `${left.repositoryOwner}/${left.repositoryName}`
      : left.registeredAt
    const rightKey = sortMode === "title"
      ? `${right.repositoryOwner}/${right.repositoryName}`
      : right.registeredAt
    const compared = leftKey.localeCompare(rightKey)
    return azDirection === "asc" ? compared : -compared
  })

  const pageCount = Math.ceil(sorted.length / PROJECT_PAGE_SIZE)
  const safePage = Math.min(Math.max(page, 1), Math.max(pageCount, 1))
  const start = (safePage - 1) * PROJECT_PAGE_SIZE
  const visible = sorted.slice(start, start + PROJECT_PAGE_SIZE)

  function countFor(filter: ProjectStatusFilter): number {
    if (filter === "ALL") {
      return projects.length
    }
    return projects.filter((project) => project.status === filter).length
  }

  function updateSearch(value: string) {
    setSearch(value)
    setPage(1)
  }

  function updateStatus(filter: ProjectStatusFilter) {
    setStatus(filter)
    setPage(1)
  }

  function updateSortMode(mode: ProjectSortMode) {
    setSortMode(mode)
    setPage(1)
  }

  function toggleAzDirection() {
    setAzDirection((direction) => (direction === "asc" ? "desc" : "asc"))
    setPage(1)
  }

  function togglePin(id: number) {
    setPinned((current) => current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id])
    setPage(1)
  }

  return { projects: visible, total: projects.length, filteredTotal: filtered.length, countFor, search, setSearch: updateSearch, status, setStatus: updateStatus, sortMode, setSortMode: updateSortMode, azDirection, toggleAzDirection, pinned, togglePin, page: safePage, pageCount, setPage, loading, loadError, refresh }
}

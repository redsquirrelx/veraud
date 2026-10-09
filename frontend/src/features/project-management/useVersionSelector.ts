import { useCallback, useEffect, useRef, useState } from "react"
import { ApiError, checkoutBranch, checkoutCommit, listBranches, listCommits, type GitCommitEntry } from "../../infrastructure/http-client/httpClient.ts"

export interface AppliedVersion {
  branch: string
  commitHash: string
}

const COMMIT_LIMIT = 30
const HASH_PATTERN = /^[0-9a-fA-F]{7,40}$/

function defaultBranch(branches: string[]): string {
  if (branches.includes("main")) {
    return "main"
  }
  if (branches.includes("master")) {
    return "master"
  }
  return branches[0] as string
}

function describeFailure(failure: unknown, fallback: string): string {
  if (failure instanceof ApiError) {
    return failure.message
  }
  return fallback
}

export function useVersionSelector(projectId: number | null, options?: { onApplied?: (version: AppliedVersion) => void }) {
  const [branches, setBranches] = useState<string[]>([])
  const [branch, setBranch] = useState("")
  const [commits, setCommits] = useState<GitCommitEntry[]>([])
  const [commitHash, setCommitHash] = useState("")
  const [detached, setDetached] = useState<string | null>(null)
  const [applied, setApplied] = useState<AppliedVersion | null>(null)
  const [loadingBranches, setLoadingBranches] = useState(false)
  const [loadingCommits, setLoadingCommits] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState("")
  const mounted = useRef(true)
  const generation = useRef(0)
  const appliedCallback = useRef(options?.onApplied)

  useEffect(() => {
    appliedCallback.current = options?.onApplied
  })

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const loadCommits = useCallback(async (id: number, name: string, token: number, markApplied: boolean) => {
    const alive = () => mounted.current && generation.current === token
    setLoadingCommits(true)
    try {
      const result = await listCommits(id, name, COMMIT_LIMIT, 0)
      if (!alive()) {
        return
      }
      setCommits(result.commits)
      const latest = result.commits[0]?.commitHash ?? ""
      setCommitHash(latest)
      if (markApplied) {
        setApplied(latest === "" ? null : { branch: name, commitHash: latest })
      }
    } catch (failure) {
      if (!alive()) {
        return
      }
      setCommits([])
      setCommitHash("")
      if (markApplied) {
        setApplied(null)
      }
      setError(describeFailure(failure, "Could not load commits"))
    } finally {
      if (alive()) {
        setLoadingCommits(false)
      }
    }
  }, [])

  const loadInitial = useCallback(async (id: number, token: number) => {
    const alive = () => mounted.current && generation.current === token
    setLoadingBranches(true)
    setError("")
    try {
      const result = await listBranches(id)
      if (!alive()) {
        return
      }
      if (result.branches.length === 0) {
        setBranches([])
        setError("No branches found in the local checkout")
        return
      }
      const hash = result.detachedHash ?? null
      setBranches(result.branches)
      setDetached(hash)
      if (hash !== null) {
        setBranch(result.currentBranch ?? defaultBranch(result.branches))
        setCommits([])
        setCommitHash(hash)
        setApplied(null)
        return
      }
      const first = result.currentBranch ?? defaultBranch(result.branches)
      setBranch(first)
      await loadCommits(id, first, token, true)
    } catch (failure) {
      if (!alive()) {
        return
      }
      setBranches([])
      setError(describeFailure(failure, "Could not load branches"))
    } finally {
      if (alive()) {
        setLoadingBranches(false)
      }
    }
  }, [loadCommits])

  useEffect(() => {
    if (projectId === null) {
      return
    }
    generation.current += 1
    void loadInitial(projectId, generation.current)
  }, [projectId, loadInitial])

  async function changeBranch(name: string) {
    if (projectId === null || (name === branch && detached === null) || loadingCommits) {
      return
    }
    generation.current += 1
    const token = generation.current
    const alive = () => mounted.current && generation.current === token
    setBranch(name)
    setApplied(null)
    setDetached(null)
    setError("")
    setLoadingCommits(true)
    try {
      await checkoutBranch(projectId, name)
      if (!alive()) {
        return
      }
      await loadCommits(projectId, name, token, true)
    } catch (failure) {
      if (!alive()) {
        return
      }
      setCommits([])
      setCommitHash("")
      setError(describeFailure(failure, "Could not check out the branch"))
      setLoadingCommits(false)
    }
  }

  async function refreshBranches() {
    if (projectId === null) {
      return
    }
    generation.current += 1
    const token = generation.current
    try {
      const result = await listBranches(projectId)
      if (!mounted.current || generation.current !== token) {
        return
      }
      setBranches(result.branches)
      const hash = result.detachedHash ?? null
      const wasDetached = detached
      setDetached(hash)
      if (hash !== null) {
        setCommits([])
        setCommitHash(hash)
        setApplied(null)
        return
      }
      if (wasDetached && branch !== "") {
        await changeBranch(branch)
      }
    } catch (failure) {
      if (!mounted.current || generation.current !== token) {
        return
      }
      setError(describeFailure(failure, "Could not load branches"))
    }
  }

  async function refresh() {
    if (projectId === null) {
      return
    }
    generation.current += 1
    await loadInitial(projectId, generation.current)
  }

  async function stageCommit(hash: string): Promise<boolean> {
    if (projectId === null || applying || loadingCommits) {
      return false
    }
    const wanted = hash.trim()
    if (HASH_PATTERN.test(wanted) === false) {
      setCommitHash(wanted)
      setError("Commit hash must be 7 to 40 hex characters")
      return false
    }
    if (applied !== null && applied.branch === branch && applied.commitHash.toLowerCase() === wanted.toLowerCase()) {
      setCommitHash(wanted)
      return true
    }
    const tip = commits[0]?.commitHash.toLowerCase() ?? ""
    const isTip = tip !== "" && (wanted.toLowerCase() === tip || tip.startsWith(wanted.toLowerCase()))
    setCommitHash(wanted)
    setApplying(true)
    setError("")
    try {
      if (isTip) {
        await checkoutBranch(projectId, branch)
        if (!mounted.current) {
          return false
        }
        setCommitHash(tip)
        setDetached(null)
        const version = { branch, commitHash: tip }
        setApplied(version)
        appliedCallback.current?.(version)
        return true
      }
      const result = await checkoutCommit(projectId, wanted)
      if (!mounted.current) {
        return false
      }
      setCommitHash(result.commitHash)
      setDetached(result.commitHash)
      setApplied(null)
      const version = { branch, commitHash: result.commitHash }
      appliedCallback.current?.(version)
      return true
    } catch (failure) {
      if (!mounted.current) {
        return false
      }
      setError(describeFailure(failure, isTip ? "Could not check out the branch" : "Could not check out the commit"))
      return false
    } finally {
      if (mounted.current) {
        setApplying(false)
      }
    }
  }

  return {
    branches,
    branch,
    commits,
    commitHash,
    detached,
    applied,
    loadingBranches,
    loadingCommits,
    applying,
    error,
    changeBranch,
    refreshBranches,
    refresh,
    stageCommit,
  }
}

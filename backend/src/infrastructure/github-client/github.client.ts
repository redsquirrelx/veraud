export interface RepoMetadata {
  id: number
  owner: string
  name: string
  cloneUrl: string
}

export class RepoNotAccessibleError extends Error {}

export function parseGithubUrl(url: string): { owner: string; repo: string } | null {
  const cleaned = url.trim().replace(/\/+$/, "").replace(/\.git$/, "")

  let parsed: URL
  
  try {
    parsed = new URL(cleaned)
  } catch {
    return null
  }

  if (parsed.hostname !== "github.com" && parsed.hostname !== "www.github.com") {
    return null
  }

  const parts = parsed.pathname.split("/").filter((part) => part.length > 0)

  if (parts.length !== 2) {
    return null
  }

  const owner = parts[0] ?? ""
  const repo = parts[1] ?? ""

  if (owner === "" || repo === "") {
    return null
  }

  return { owner, repo }
}

export class GithubClient {
  async checkAccess(owner: string, repo: string): Promise<RepoMetadata> {
    const response = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "veraud-backend",
      },
    })

    if (!response.ok) {
      throw new RepoNotAccessibleError(
        `Repository ${owner}/${repo} is not accessible (GitHub returned ${response.status})`
      )
    }

    const data = (await response.json()) as { id: number; name: string; clone_url: string }

    return { id: data.id, owner, name: data.name, cloneUrl: data.clone_url }
  }
}

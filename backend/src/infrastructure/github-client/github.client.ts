export interface RepoMetadata {
  id: number
  owner: string
  name: string
  cloneUrl: string
}

export class RepoNotAccessibleError extends Error {}

export function parseGithubUrl(url: string): { owner: string; repo: string; protocol: "https" | "ssh" } | null {
  const cleaned = url.trim().replace(/\/+$/, "").replace(/\.git$/, "")
  const scp = /^git@github\.com:([^/]+\/[^/]+)$/.exec(cleaned)
  let path: string
  let protocol: "https" | "ssh"

  if (scp !== null) {
    path = scp[1] ?? ""
    protocol = "ssh"
  } else {
    let parsed: URL
    try {
      parsed = new URL(cleaned)
    } catch {
      return null
    }
    if ((parsed.protocol === "https:" && (parsed.hostname === "github.com" || parsed.hostname === "www.github.com") && parsed.username === "" && parsed.password === "" && parsed.port === "") ||
        (parsed.protocol === "ssh:" && parsed.hostname === "github.com" && parsed.username === "git" && parsed.password === "" && parsed.port === "")) {
      path = parsed.pathname.replace(/^\//, "")
      protocol = parsed.protocol === "ssh:" ? "ssh" : "https"
    } else {
      return null
    }
    if (parsed.search !== "" || parsed.hash !== "") {
      return null
    }
  }

  const parts = path.split("/")
  const owner = parts[0] ?? ""
  const repo = parts[1] ?? ""
  if (parts.length !== 2 || !/^[A-Za-z0-9-]+$/.test(owner) || !/^[A-Za-z0-9_.-]+$/.test(repo) || repo === "." || repo === "..") {
    return null
  }
  return { owner, repo, protocol }
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

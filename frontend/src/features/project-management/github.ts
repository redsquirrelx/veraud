export function githubRepoUrl(owner: string, name: string): string {
  return `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`
}

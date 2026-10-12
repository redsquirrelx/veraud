export function projectWorkspaceFolder(project: { id: number; githubRepositoryId: bigint | null; repositoryOwner: string; repositoryName: string }): string {
  const prefix = project.githubRepositoryId === null ? `project-${project.id}` : String(project.githubRepositoryId)
  return `${prefix}-${project.repositoryOwner}-${project.repositoryName}`
}

import type { PrismaClient } from "../../generated/prisma/client.js"

export interface NewProject {
  githubRepositoryId: bigint
  repositoryOwner: string
  repositoryName: string
  status: string
}

export interface StoredProject {
  id: number
  repositoryOwner: string
  repositoryName: string
  status: string
}

export interface StoredProjectDetails {
  id: number
  repositoryOwner: string
  repositoryName: string
  status: string
  registeredAt: Date
  branch: string | null
  commitHash: string | null
}

export interface ProjectStore {
  create(data: NewProject): Promise<StoredProject>
  findByGithubId(githubRepositoryId: bigint): Promise<StoredProject | null>
  delete(id: number): Promise<void>
  setStatus(id: number, status: string): Promise<void>
  list(): Promise<StoredProjectDetails[]>
}

export class ProjectRepository implements ProjectStore {
  constructor(private db: PrismaClient) {}

  async create(data: NewProject): Promise<StoredProject> {
    const project = await this.db.project.create({ data })
    return {
      id: project.id,
      repositoryOwner: project.repositoryOwner,
      repositoryName: project.repositoryName,
      status: project.status,
    }
  }

  async findByGithubId(githubRepositoryId: bigint): Promise<StoredProject | null> {
    const project = await this.db.project.findUnique({ where: { githubRepositoryId } })

    if (project === null) {
      return null
    }

    return {
      id: project.id,
      repositoryOwner: project.repositoryOwner,
      repositoryName: project.repositoryName,
      status: project.status,
    }
  }

  async delete(id: number): Promise<void> {
    await this.db.project.delete({ where: { id } })
  }

  async setStatus(id: number, status: string): Promise<void> {
    await this.db.project.update({ where: { id }, data: { status } })
  }

  async list(): Promise<StoredProjectDetails[]> {
    const projects = await this.db.project.findMany({
      orderBy: { id: "asc" },
      include: { selectedVersion: true },
    })
    return projects.map((project) => ({
      id: project.id,
      repositoryOwner: project.repositoryOwner,
      repositoryName: project.repositoryName,
      status: project.status,
      registeredAt: project.createdAt,
      branch: project.selectedVersion?.branch ?? null,
      commitHash: project.selectedVersion?.commitHash ?? null,
    }))
  }
}

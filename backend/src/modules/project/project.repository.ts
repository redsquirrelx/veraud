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
  githubRepositoryId: bigint
  repositoryOwner: string
  repositoryName: string
  status: string
  registeredAt: Date
  lastSyncedAt: Date | null
  branch: string | null
  commitHash: string | null
}

export interface ProjectStore {
  create(data: NewProject): Promise<StoredProject>
  findByGithubId(githubRepositoryId: bigint): Promise<StoredProject | null>
  findById(id: number): Promise<StoredProjectDetails | null>
  delete(id: number): Promise<void>
  setStatus(id: number, status: string): Promise<void>
  markSynced(id: number, at: Date): Promise<void>
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

  async findById(id: number): Promise<StoredProjectDetails | null> {
    const project = await this.db.project.findUnique({
      where: { id },
      include: { selectedVersion: true },
    })

    if (project === null) {
      return null
    }

    return this.toDetails(project)
  }

  async setStatus(id: number, status: string): Promise<void> {
    await this.db.project.update({ where: { id }, data: { status } })
  }

  async markSynced(id: number, at: Date): Promise<void> {
    await this.db.project.update({ where: { id }, data: { lastSyncedAt: at } })
  }

  async list(): Promise<StoredProjectDetails[]> {
    const projects = await this.db.project.findMany({
      orderBy: { id: "asc" },
      include: { selectedVersion: true },
    })
    return projects.map((project) => this.toDetails(project))
  }

  private toDetails(project: {
    id: number
    githubRepositoryId: bigint
    repositoryOwner: string
    repositoryName: string
    status: string
    createdAt: Date
    lastSyncedAt: Date | null
    selectedVersion: { branch: string | null; commitHash: string | null } | null
  }): StoredProjectDetails {
    return {
      id: project.id,
      githubRepositoryId: project.githubRepositoryId,
      repositoryOwner: project.repositoryOwner,
      repositoryName: project.repositoryName,
      status: project.status,
      registeredAt: project.createdAt,
      lastSyncedAt: project.lastSyncedAt,
      branch: project.selectedVersion?.branch ?? null,
      commitHash: project.selectedVersion?.commitHash ?? null,
    }
  }
}

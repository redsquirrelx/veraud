import type { PrismaClient } from "../../generated/prisma/client.js"

export interface NewTask {
  projectId: number
  description: string
  status: string
}

export interface TaskUpdate {
  status: string
  exitCode: number | null
  logTrail: string | null
}

export interface StoredTask {
  id: number
  projectId: number
  repositoryOwner: string
  repositoryName: string
  description: string | null
  status: string
  exitCode: number | null
}

export interface TaskStore {
  create(data: NewTask): Promise<StoredTask>
  update(id: number, data: TaskUpdate): Promise<StoredTask>
  delete(id: number): Promise<void>
  findById(id: number): Promise<StoredTask | null>
  findActive(): Promise<StoredTask[]>
}

export class TaskRepository implements TaskStore {
  constructor(private db: PrismaClient) {}

  async create(data: NewTask): Promise<StoredTask> {
    const task = await this.db.task.create({ data, include: { project: true } })
    return this.toStored(task)
  }

  async update(id: number, data: TaskUpdate): Promise<StoredTask> {
    const task = await this.db.task.update({ where: { id }, data, include: { project: true } })
    return this.toStored(task)
  }

  async delete(id: number): Promise<void> {
    await this.db.task.delete({ where: { id } })
  }

  async findById(id: number): Promise<StoredTask | null> {
    const task = await this.db.task.findUnique({ where: { id }, include: { project: true } })

    if (task === null) {
      return null
    }

    return this.toStored(task)
  }

  async findActive(): Promise<StoredTask[]> {
    const tasks = await this.db.task.findMany({
      where: { status: { in: ["Queued", "Running"] } },
      orderBy: { id: "asc" },
      include: { project: true },
    })
    return tasks.map((task) => this.toStored(task))
  }

  private toStored(task: {
    id: number
    projectId: number
    description: string | null
    status: string
    exitCode: number | null
    project: { repositoryOwner: string; repositoryName: string }
  }): StoredTask {
    return {
      id: task.id,
      projectId: task.projectId,
      repositoryOwner: task.project.repositoryOwner,
      repositoryName: task.project.repositoryName,
      description: task.description,
      status: task.status,
      exitCode: task.exitCode,
    }
  }
}

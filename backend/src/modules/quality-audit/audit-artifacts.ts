import { createReadStream } from "node:fs"
import { readFile, stat } from "node:fs/promises"
import { join, resolve } from "node:path"
import { auditReportSections, type AuditReportSection } from "./audit-report-sections.js"

export const auditArtifactFormat = "veraud.audit.artifacts.v1"

export interface AuditArtifactManifest {
  format: string
  run_id: string
  report_bytes: number
  docx_bytes: number
  sections: string[]
}

const runIdPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/

export function parseArtifactManifest(value: unknown): AuditArtifactManifest | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const candidate = value as Record<string, unknown>
  if (candidate.format !== auditArtifactFormat
    || typeof candidate.run_id !== "string" || !runIdPattern.test(candidate.run_id)
    || typeof candidate.report_bytes !== "number" || !Number.isSafeInteger(candidate.report_bytes) || candidate.report_bytes < 0
    || typeof candidate.docx_bytes !== "number" || !Number.isSafeInteger(candidate.docx_bytes) || candidate.docx_bytes < 0
    || !Array.isArray(candidate.sections) || candidate.sections.some((section) => !auditReportSections.includes(section as AuditReportSection))) return null
  return candidate as unknown as AuditArtifactManifest
}

export class AuditArtifactStore {
  private readonly root: string

  constructor(workspaceDir?: string, artifactDir = process.env.VERAUD_ARTIFACT_DIR) {
    this.root = resolve(artifactDir ?? join(workspaceDir ?? process.cwd(), ".veraud-artifacts"))
  }

  path(manifest: AuditArtifactManifest, file: "report.json" | "report.docx"): string {
    return join(this.root, manifest.run_id, file)
  }

  sectionPath(manifest: AuditArtifactManifest, section: AuditReportSection): string {
    return join(this.root, manifest.run_id, "sections", `${section}.json`)
  }

  async readSection(manifest: AuditArtifactManifest, section: AuditReportSection): Promise<unknown> {
    return JSON.parse(await readFile(this.sectionPath(manifest, section), "utf8")) as unknown
  }

  /** Read the verification-suite build summary that the agent-server writes next to the artifacts.
   *  Returns null when the build has not finished or the file is not a valid summary — callers
   *  must treat it as "not ready", never as an error of the artifact reader. */
  async verificationSuiteSummary(manifest: AuditArtifactManifest): Promise<Record<string, unknown> | null> {
    try {
      const parsed = JSON.parse(await readFile(join(this.root, manifest.run_id, "verification-suite-summary.json"), "utf8")) as unknown
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null
      const candidate = parsed as Record<string, unknown>
      if (candidate.run_id !== manifest.run_id || !Array.isArray(candidate.verifications) || typeof candidate.validation_status !== "string") return null
      return candidate
    } catch {
      return null
    }
  }

  async assertAvailable(manifest: AuditArtifactManifest): Promise<void> {
    const [report, docx] = await Promise.all([stat(this.path(manifest, "report.json")), stat(this.path(manifest, "report.docx"))])
    if (!report.isFile() || !docx.isFile() || report.size !== manifest.report_bytes || docx.size !== manifest.docx_bytes) {
      throw new Error("Audit artifact store is incomplete or inconsistent")
    }
  }

  open(manifest: AuditArtifactManifest, file: "report.json" | "report.docx") {
    return createReadStream(this.path(manifest, file))
  }
}

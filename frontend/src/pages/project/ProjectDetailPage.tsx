import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, Navigate, useNavigate, useParams } from "react-router-dom"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { ApiError, listProjects, syncProject, type AgentExecution, type ProjectSummary, type VersionAnalysisSummary } from "../../infrastructure/http-client/httpClient.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { mergeExecution } from "../../shared/agent-monitor/mergeExecution.ts"
import { useTasks } from "../../shared/task-manager/useTasks.ts"
import { isSyncActive } from "../../shared/task-manager/taskVisibility.ts"
import {
  OrientationResultView,
  PipelineRunStatus,
  ProjectArchitectureResultView,
  SemanticValidationResultView,
  StageStatusView,
} from "../../features/project-management/PipelineResult.tsx"
import {
  parseOrientationResult,
  parseProjectArchitectureResult,
  parseSemanticValidationResult,
  verdictTone,
} from "../../features/project-management/pipelineResult.ts"
import { CodeViewer, DirectoryTree, Badge, Button, Card, FolderIcon, Spinner, ExternalIcon, SplitView } from "../../shared/ui-kit/index.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { ProjectSidebar } from "./ProjectSidebar.tsx"
import { ProjectOverviewIcon, ProjectAnalysisIcon, ProjectAuditsIcon } from "./projectSectionIcons.tsx"
import { ProjectHeader } from "./ProjectHeader.tsx"
import { githubRepoUrl } from "../../features/project-management/github.ts"
import { reviewVerdictLabelKeys, statusLabelKey } from "../../features/project-management/projectStatus.ts"
import { useVersionSelector } from "../../features/project-management/useVersionSelector.ts"
import { useAnalyzedVersions } from "../../features/project-management/useAnalyzedVersions.ts"
import { useAnalysis } from "../../features/project-management/useAnalysis.ts"
import { QualityAudits } from "../../features/project-management/QualityAudits.tsx"
import { QualityAuditResults } from "../../features/project-management/QualityAuditResults.tsx"
import { AuditAgentEvidence } from "../../features/project-management/AuditAgentEvidence.tsx"
import { useProjectFile } from "../../features/project-management/useProjectFile.ts"
import { useProjectTree } from "../../features/project-management/useProjectTree.ts"
import type { VersionMode } from "../../features/project-management/VersionSelector.tsx"
import { useToasts } from "../../app/use-toasts.ts"
import { formatDate, formatNumber } from "../../shared/i18n/format.ts"
import "./ProjectDetailPage.css"

const sectionItems: Array<{ id: string, labelKey: ParseKeys<"projects">, icon: ReactNode }> = [
  { id: "overview", labelKey: "detail.sections.overview", icon: <ProjectOverviewIcon /> },
  { id: "analysis", labelKey: "detail.sections.analysis", icon: <ProjectAnalysisIcon /> },
  { id: "audits", labelKey: "detail.sections.audits", icon: <ProjectAuditsIcon /> },
  { id: "files", labelKey: "detail.sections.files", icon: <FolderIcon /> },
]

const VALID_SECTIONS = new Set(sectionItems.map((item) => item.id))

export function ProjectDetailPage() {
  const { id, section, auditId, invocationId } = useParams()
  const { t } = useTranslation("projects")
  const navigate = useNavigate()
  const activeSection = auditId !== undefined ? "audits" : section !== undefined && VALID_SECTIONS.has(section) ? section : "overview"
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [syncing, setSyncing] = useState(false)
  const { pushToast } = useToasts()
  const version = useVersionSelector(project?.id ?? null, {
    onApplied: (applied) => {
      pushToast("success", t("detail.versionApplied", { branch: applied.branch, shortHash: applied.commitHash.slice(0, 7) }))
    },
  })
  const files = useProjectTree(project?.id ?? null, project?.repositoryName ?? "")
  const preview = useProjectFile(project?.id ?? null)
  const analysis = useAnalysis(project?.id ?? null)
  const analyzed = useAnalyzedVersions(project?.id ?? null)
  const [versionMode, setVersionMode] = useState<VersionMode>("git")
  const [analyzedId, setAnalyzedId] = useState<number | null>(null)
  const notifiedExecution = useRef<number | null>(null)
  const refreshedExecution = useRef<number | null>(null)
  const analyzedVersions = analyzed.versions.filter((item) => item.evaluationId !== null)
  const selectedAnalyzed = analyzedVersions.find((item) => item.id === analyzedId) ?? null
  const refreshFiles = files.refresh
  const clearPreview = preview.clear
  const refreshAnalyzed = analyzed.refresh
  // The tracked run is the one that finishes last for the running pipeline,
  // so its companions are the other rows of the same evaluation: live first,
  // then the stored versions once they refresh. Old single-row versions only
  // ever yield the analyzer.
  const tracked = analysis.execution
  const liveExecutions = useAgentExecutions()
  const liveTasks = useTasks()
  const analyzerExec = stageExecution("analyzer", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const architectExec = stageExecution("architect", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const orientationExec = stageExecution("orientation", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const projectArchitectureExec = stageExecution("architecture", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const semanticValidationExec = stageExecution("semantic_validation", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const orientationSummary = orientationExec === null ? null : parseOrientationResult(orientationExec.result)
  const projectArchitectureSummary = projectArchitectureExec === null ? null : parseProjectArchitectureResult(projectArchitectureExec.result)
  const semanticValidationSummary = semanticValidationExec === null ? null : parseSemanticValidationResult(semanticValidationExec.result)
  const versionKey = `${version.applied?.branch ?? ""}:${version.applied?.commitHash ?? ""}:${version.detached ?? ""}`
  const activeHash = version.detached ?? version.applied?.commitHash ?? null
  const activeBranch = version.applied?.branch ?? selectedAnalyzed?.branch ?? null
  // Sync and analysis exclude each other: a sync rewrites the checkout the
  // pipeline reads. Local clicks flip immediately; a sync started elsewhere
  // shows up through the live tasks and through the backend 422.
  const syncActive = syncing || isSyncActive(liveTasks, project?.id ?? null)
  const canAnalyze = activeHash !== null && activeBranch !== null && !version.applying && !version.loadingCommits && !syncActive

  function openFile(path: string) {
    const root = project?.repositoryName ?? ""
    const relative = root !== "" && path.startsWith(`${root}/`) ? path.slice(root.length + 1) : path
    preview.open(relative)
  }

  async function handleSync() {
    if (project === null || syncing) {
      return
    }
    setSyncing(true)
    try {
      const updated = await syncProject(project.id)
      setProject(updated)
      pushToast("success", t("detail.sync.success", { name: `${updated.repositoryOwner}/${updated.repositoryName}` }))
      await version.refresh()
      clearPreview()
      refreshFiles()

    } catch (error) {
      if (error instanceof ApiError && error.messageSource !== "client") {
        pushToast("error", error.message)
      } else {
        pushToast("error", t("detail.sync.errorFallback"))
      }
    } finally {
      setSyncing(false)
    }
  }

  useEffect(() => {
    let alive = true
    listProjects().then(
      (rows) => {
        if (alive) {
          setProject(rows.find((row) => row.id === Number(id)) ?? null)
          setLoadError("")
          setLoading(false)
        }
      },
      () => {
        if (alive) {
          setProject(null)
          setLoadError(t("detail.loadError"))
          setLoading(false)
        }
      }
    )
    return () => {
      alive = false
    }
  }, [id, t])

  // single driver: entering the files section and any version change refetch the tree
  useEffect(() => {
    if (activeSection === "files") {
      clearPreview()
      refreshFiles()
    }
  }, [activeSection, versionKey, refreshFiles, clearPreview])

  // analyzed versions load lazily when their tab opens
  useEffect(() => {
    if (versionMode === "analyzed") {
      refreshAnalyzed()
    }
  }, [versionMode, refreshAnalyzed])

  useEffect(() => {
    if (analysis.phase === "error" && analysis.message !== "") {
      pushToast("error", analysis.message)
    }
  }, [analysis.phase, analysis.message, pushToast])

  useEffect(() => {
    const finished = analysis.execution
    if (analysis.phase !== "done" || finished === null || !analysis.tracked || notifiedExecution.current === finished.id) {
      return
    }
    notifiedExecution.current = finished.id
    if (finished.status === "Completed") {
      pushToast("success", t("analysis.completed"))
    } else {
      pushToast("error", finished.error ?? t("analysis.failed"))
    }
  }, [analysis.phase, analysis.execution, analysis.tracked, pushToast, t])

  useEffect(() => {
    const finished = analysis.execution
    if (analysis.phase !== "done" || finished === null || refreshedExecution.current === finished.id) {
      return
    }
    refreshedExecution.current = finished.id
    void refreshAnalyzed()
  }, [analysis.phase, analysis.execution, refreshAnalyzed])

  function handleAnalyze(pipelineId: string) {
    if (activeBranch === null || activeHash === null) {
      return
    }
    void analysis.start(activeBranch, activeHash, pipelineId)
  }

  /** Picks an analyzed version: checks out its commit, then shows its run. */
  async function selectAnalyzed(id: number) {
    const target = analyzedVersions.find((item) => item.id === id) ?? null
    if (target === null || target.commitHash === null) {
      return
    }
    const landed = await version.stageCommit(target.commitHash)
    if (!landed) {
      return
    }
    setAnalyzedId(id)
    // The semantic_validation row carries the final verdict; fall back through
    // the other project stages, then to legacy rows when an old version only
    // has those.
    analysis.show(
      target.executions.find((execution) => execution.agentType === "semantic_validation")
        ?? target.executions.find((execution) => execution.agentType === "architecture")
        ?? target.executions.find((execution) => execution.agentType === "orientation")
        ?? target.executions.find((execution) => execution.agentType === "architect")
        ?? target.executions.find((execution) => execution.agentType === "analyzer")
        ?? null,
    )
  }

  function handleModeChange(next: VersionMode) {
    setVersionMode(next)
    if (next === "git") {
      setAnalyzedId(null)
      analysis.show(null)
    }
  }

  const gitSelection = {
    ...version,
    changeBranch: (name: string) => {
      setAnalyzedId(null)
      analysis.show(null)
      return version.changeBranch(name)
    },
    stageCommit: (hash: string) => {
      setAnalyzedId(null)
      analysis.show(null)
      return version.stageCommit(hash)
    },
  }

  const runStatuses = (
    <>
      {analyzerExec !== null && <PipelineRunStatus execution={analyzerExec} />}
      {architectExec !== null && <PipelineRunStatus execution={architectExec} />}
      {orientationExec !== null && <PipelineRunStatus execution={orientationExec} />}
      {projectArchitectureExec !== null && <PipelineRunStatus execution={projectArchitectureExec} />}
      {semanticValidationExec !== null && <PipelineRunStatus execution={semanticValidationExec} />}
    </>
  )

  if (section !== undefined && !VALID_SECTIONS.has(section)) {
    return <Navigate to={`/projects/${id}/overview`} replace />
  }
  if (auditId !== undefined && (!/^[1-9]\d*$/.test(auditId) || !Number.isSafeInteger(Number(auditId)))) {
    return <Navigate to={`/projects/${id}/audits`} replace />
  }

  return (
    <section className="project-page">
      <ProjectSidebar items={sectionItems.map((item) => ({ id: item.id, label: t(item.labelKey), icon: item.icon }))} activeId={activeSection} onSelect={(next) => void navigate(`/projects/${id}/${next}`)} />
      <div className="project-content">
        {loading ? (
          <p className="label" role="status">{t("detail.loading")}</p>
        ) : loadError !== "" ? (
          <p role="alert">{loadError}</p>
        ) : project === null ? (
          <p>{t("detail.notFound")}</p>
        ) : (
          <>
            <ProjectHeader
              project={project}
              analysis={{ canAnalyze, analyzing: analysis.analyzing, onAnalyze: handleAnalyze }}
              syncing={syncActive}
              onSync={() => void handleSync()}
               onAudit={() => void navigate(`/projects/${id}/analysis`)}
              versionSelector={{
                selection: gitSelection,
                mode: versionMode,
                onModeChange: handleModeChange,
                analyzed: {
                  versions: analyzedVersions,
                  loading: analyzed.loading,
                  error: analyzed.error,
                  selectedId: analyzedId,
                  onSelect: (id) => void selectAnalyzed(id),
                  onRefresh: () => void analyzed.refresh(),
                },
              }}
            />
            <div className="project-body">
            {activeSection === "overview" && <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
              <section className="project-overview" aria-label={t("detail.overview.regionLabel")}>
                <h2>{t("detail.overview.title")}</h2>
                <div className="project-dates-row">
                  <span className="project-date">
                    {t("detail.overview.registeredAt", { date: formatDate(project.registeredAt) })}
                  </span>
                  <span className="project-date">
                    {project.lastSyncedAt === null
                      ? t("detail.overview.neverSynced")
                      : t("detail.overview.lastSynced", { date: formatDate(project.lastSyncedAt) })}
                  </span>
                </div>
                <a
                  className="ui-button ui-button-secondary"
                  href={githubRepoUrl(project.repositoryOwner, project.repositoryName)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("detail.overview.openOnGitHub")}<ExternalIcon size={12} />
                </a>
                {analysis.analyzing && (
                <div className="files-loading" role="status" aria-label={t("detail.files.loading")}>
                  <Spinner />
                  <span className="label">{t("detail.overview.analyzing")}</span>
                </div>
              )}
              </section>
            </Card>}
            {activeSection === "overview" && analysis.execution !== null
              && (orientationSummary !== null || projectArchitectureSummary !== null
                || semanticValidationSummary !== null) && (
              <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                <div className="audit-block">
                  <div className="audit-head">
                    <h4 className="audit-title">{t("detail.overview.summary")}</h4>
                    <div className="audit-head-right">
                      <div className="audit-status-row">
                        {orientationSummary !== null && orientationSummary.projectType !== "" && (
                          <>
                            <span className="label">{t("detail.overview.projectType")}</span>
                            <Badge tone="info">{orientationSummary.projectType}</Badge>
                          </>
                        )}
                        {projectArchitectureSummary !== null && projectArchitectureSummary.pattern !== "" && (
                          <>
                            <span className="label">{t("detail.overview.pattern")}</span>
                            <Badge tone="info">{projectArchitectureSummary.pattern}</Badge>
                          </>
                        )}
                        {semanticValidationSummary !== null && (
                          <>
                            <span className="label">{t("detail.overview.review")}</span>
                            <Badge tone={verdictTone(semanticValidationSummary.verdict)}>{(() => {
                              const verdictKey = statusLabelKey(reviewVerdictLabelKeys, semanticValidationSummary.verdict)
                              return verdictKey === null ? semanticValidationSummary.verdict : t(verdictKey)
                            })()}</Badge>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="audit-button-row">
                    <Button onClick={() => void navigate(`/projects/${id}/analysis`)}>
                      {t("detail.overview.viewFullAnalysis")}
                    </Button>
                  </div>
                </div>
              </Card>
            )}
             {(activeSection === "analysis" || activeSection === "audits") && auditId === undefined && (
               <QualityAudits key={project.id} projectId={project.id} branch={activeBranch} commitHash={activeHash}
                 canRun={canAnalyze && !analysis.analyzing} cardLayout="stack" cardPadding="default"
                 view={activeSection === "analysis" ? "configuration" : "history"}
                 onConfigure={() => void navigate(`/projects/${id}/analysis`)} />
             )}
             {activeSection === "analysis" && analysis.execution !== null && (
              <>
                {analyzerExec !== null && (
                  <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                    <PipelineRunStatus execution={analyzerExec} />
                  </Card>
                )}
                {architectExec !== null && (
                  <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                    <PipelineRunStatus execution={architectExec} />
                  </Card>
                )}
                {orientationExec !== null && (
                  <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                    {orientationSummary !== null
                      ? <OrientationResultView summary={orientationSummary} execution={orientationExec} />
                      : <StageStatusView title={t("pipeline.orientationTitle")} result={orientationExec.result} execution={orientationExec} />}
                  </Card>
                )}
                {projectArchitectureExec !== null && (
                  <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                    {projectArchitectureSummary !== null
                      ? <ProjectArchitectureResultView summary={projectArchitectureSummary} execution={projectArchitectureExec} />
                      : <StageStatusView title={t("pipeline.architectureTitle")} result={projectArchitectureExec.result} execution={projectArchitectureExec} />}
                  </Card>
                )}
                {semanticValidationExec !== null && (
                  <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                    {semanticValidationSummary !== null
                      ? <SemanticValidationResultView summary={semanticValidationSummary} execution={semanticValidationExec} />
                      : <StageStatusView title={t("pipeline.semanticTitle")} result={semanticValidationExec.result} execution={semanticValidationExec} />}
                  </Card>
                )}
              </>
            )}
            {activeSection === "files" && (
              <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                <SplitView
                  label={t("detail.files.resizeLabel")}
                  right={
                    preview.loading && preview.file === null ? (
                      <div className="files-loading" role="status" aria-label={t("detail.files.loading")}>
                        <Spinner />
                        <span className="label">{t("detail.files.loadingFile")}</span>
                      </div>
                    ) : preview.error !== "" ? (
                      <p className="files-error">{preview.error}</p>
                    ) : preview.file === null ? (
                      <p className="label files-empty">{t("detail.files.selectFile")}</p>
                    ) : (
                      <CodeViewer code={preview.file.content} language={fileLanguage(preview.file.path)} highlight />
                    )
                  }
                  left={
                    files.loading && files.tree === null ? (
                      <div className="files-loading" role="status" aria-label={t("detail.files.loading")}>
                        <Spinner />
                        <span className="label">{t("detail.files.loadingFiles")}</span>
                      </div>
                    ) : files.error !== "" ? (
                      <p className="files-error">{files.error}</p>
                    ) : files.tree === null ? (
                      <p className="label">{t("detail.files.noFiles")}</p>
                    ) : (
                      <DirectoryTree tree={files.tree} onRefresh={files.refresh} onSelectFile={openFile} />
                    )
                  }
                />
              </Card>
            )}
            {auditId !== undefined && (invocationId !== undefined
              ? <AuditAgentEvidence projectId={project.id} auditId={Number(auditId)} invocationId={invocationId} projectName={`${project.repositoryOwner}/${project.repositoryName}`} repositoryName={project.repositoryName} />
              : <QualityAuditResults key={`${project.id}-${auditId}`} projectId={project.id} auditId={Number(auditId)} projectName={`${project.repositoryOwner}/${project.repositoryName}`} repositoryName={project.repositoryName} />)}
             {activeSection === "analysis" && auditId === undefined && (
              analysis.execution === null ? (
                null
              ) : (
                <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
                  {runStatuses}
                  {[orientationExec, projectArchitectureExec, semanticValidationExec, analyzerExec, architectExec].some((execution) => execution?.status === "Failed" && execution.result) && <Link className="ui-button ui-button-secondary" to={`/projects/${id}/analysis`}>{t("detail.audits.viewPartial")}</Link>}
                  {[orientationExec, projectArchitectureExec, semanticValidationExec, analyzerExec, architectExec].filter((execution) => execution?.configuration).map((execution) => execution && <div className="audit-configuration" key={execution.id}>
                    <h3>{t("detail.audits.configuration.title")}</h3>
                    <p className="label">{t("detail.audits.configuration.capturedFor", { agentType: execution.agentType, id: execution.id })}</p>
                    <dl>
                      <dt>{t("detail.audits.configuration.model")}</dt><dd>{execution.configuration!.model.name}</dd>
                      <dt>{t("detail.audits.configuration.provider")}</dt><dd>{execution.configuration!.model.providerName}</dd>
                      <dt>{t("detail.audits.configuration.credential")}</dt><dd>{t("detail.audits.configuration.credentialValue", { name: execution.configuration!.credential.name, id: execution.configuration!.credential.id })}</dd>
                      <dt>{t("detail.audits.configuration.temperature")}</dt><dd>{execution.configuration!.temperature}</dd>
                       <dt>{t("detail.audits.configuration.maxTokens")}</dt><dd>{execution.configuration!.maxTokens}</dd>
                       <dt>{t("detail.audits.configuration.tokenBudget")}</dt><dd>{execution.configuration!.tokenBudget == null ? t("detail.audits.configuration.notRecorded") : formatNumber(execution.configuration!.tokenBudget)}</dd>
                       <dt>{t("detail.audits.configuration.absoluteLimit")}</dt><dd>{execution.configuration!.absoluteTokenLimit == null ? t("detail.audits.configuration.notRecorded") : formatNumber(execution.configuration!.absoluteTokenLimit)}</dd>
                    </dl>
                    <p className="label">{t("detail.audits.configuration.note")}</p>
                  </div>)}
                </Card>
              )
            )}
             {auditId === undefined && activeSection !== "audits" && analysis.phase === "error" && <Card className="project-body-card" layout="stack" gap="md" align="stretch" padding="responsive">
              <p role="alert">{analysis.message}</p>
             <Link className="ui-button ui-button-secondary" to="/settings" onClick={() => localStorage.set("settings.activeTab", "agents")}>{t("detail.reviewAgents")}</Link>
            </Card>}
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function fileLanguage(path: string): string {
  const dot = path.lastIndexOf(".")
  return dot < 0 ? "" : path.slice(dot + 1).toLowerCase()
}

/** One pipeline row of the tracked evaluation, if it is known. */
function stageExecution(
  stage: string,
  tracked: AgentExecution | null,
  live: AgentExecution[],
  versions: VersionAnalysisSummary[],
  initial: AgentExecution[],
): AgentExecution | null {
  if (tracked?.agentType === stage) {
    return tracked
  }
  if (tracked === null || tracked.evaluationId === null) {
    return initial.find((item) => item?.agentType === stage) ?? null
  }
  const clean = (rows: AgentExecution[]): AgentExecution[] =>
    rows.filter((item): item is AgentExecution => item !== null && typeof item === "object")
  const match = (rows: AgentExecution[]): AgentExecution | null => clean(rows).find(
    (item) => item.evaluationId === tracked.evaluationId && item.agentType === stage,
  ) ?? null
  const current = match(live)
  const stored = match(versions.flatMap((version) => version.executions)) ?? match(initial)
  if (current === null) {
    return stored
  }
  return mergeExecution(stored, current)
}

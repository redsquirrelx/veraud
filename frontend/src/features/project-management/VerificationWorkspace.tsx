import { useState, useEffect } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button, Card, CodeIcon, CodeViewer, FilterTabs, ItemSelector, ListIcon, ShieldIcon, Spinner } from "../../shared/ui-kit/index.ts"
import { listVerificationCommits, type VerificationCommitEntry } from "./qualityAuditApi.ts"
import type { SuiteAction, VerificationEntry, VerificationSuitePage } from "./qualityAuditApi.ts"
import { useAuditSourceFile } from "./useAuditSourceFile.ts"
import "./VerificationWorkspace.css"

type Outcome = "passed" | "violation" | "error" | "other"
function verificationOutcome(status: string): Outcome {
  if (status === "VERIFIED_FIXED") return "passed"
  if (status === "VIOLATION_PRESENT") return "violation"
  if (status === "EXECUTION_ERROR") return "error"
  return "other"
}

function CommitAncestorSelector(props: { projectId: number, auditId: number, disabled: boolean, selected: string | null, onSelect: (hash: string) => void }) {
  const { t } = useTranslation("projects")
  const [commits, setCommits] = useState<VerificationCommitEntry[]>([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    listVerificationCommits(props.projectId, props.auditId, 30, 0).then((page) => {
      if (cancelled) return
      setCommits(page.commits)
      setOffset(page.commits.length)
      setHasMore(page.hasMore)
      setLoading(false)
    }, () => { if (!cancelled) { setFailed(true); setLoading(false) } })
    return () => { cancelled = true }
  }, [props.projectId, props.auditId])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const page = await listVerificationCommits(props.projectId, props.auditId, 30, offset)
      setCommits((current) => [...current, ...page.commits])
      setOffset(offset + page.commits.length)
      setHasMore(page.hasMore)
    } catch { setFailed(true) }
    finally { setLoadingMore(false) }
  }

  return <div className="verification-commit-selector">
    <ItemSelector
      label={t("verificationWorkspace.descendantsLabel")}
      placeholder={failed ? t("verificationWorkspace.commitLoadError") : t("verificationWorkspace.noRequestedCommit")}
      items={commits.map((commit) => ({ id: commit.commitHash, label: commit.commitHash.slice(0, 10), detail: commit.subject }))}
      selectedId={props.selected}
      onSelect={props.onSelect}
      hasMore={hasMore}
      loadingMore={loadingMore}
      onLoadMore={() => void loadMore()}
      emptyText={t("verificationWorkspace.noDescendants")}
      loadMoreText={t("verificationWorkspace.loadMoreCommits")}
      loading={loading}
      disabled={props.disabled}
      size="compact"
    />
    {failed && commits.length === 0 && <p role="alert" className="verification-muted">{t("verificationWorkspace.descendantsUnavailable")}</p>}
  </div>
}

export function SourcePreview({ projectId, auditId, commit, path }: { projectId: number, auditId: number, commit: string, path: string }) {
  const { t } = useTranslation("projects")
  const source = useAuditSourceFile(projectId, auditId, path, commit)
  return <div className="verification-source">
    <p>{t("verificationWorkspace.baselineSource")} · <code>{commit}</code></p>
    {source.loading ? <Spinner /> : source.file ? <CodeViewer code={source.file.content} language={path.split(".").pop()} />
      : <p>{t("verificationWorkspace.sourceUnavailable")}</p>}
  </div>
}

function VerificationRow({ entry, projectId, auditId, baseline }: { entry: VerificationEntry, projectId: number, auditId: number, baseline: string }) {
  const { t } = useTranslation("projects")
  const [source, setSource] = useState<string | null>(null)
  const outcome = verificationOutcome(entry.status)
  const paths = (entry.target_components ?? []).filter((path) => !/^(?:[a-z]:|[/\\])|(?:^|[/\\])\.\.(?:[/\\]|$)/i.test(path))
  return <details className="verification-row">
    <summary>
      <span className="verification-row-main"><code>{entry.verification_id}</code><span className="verification-description">{entry.covered_property}</span></span>
      <span className="verification-badges"><Badge tone={outcome === "passed" ? "success" : outcome === "violation" ? "danger" : "warning"}>
        {outcome === "other" ? entry.status : t(`verificationWorkspace.${outcome}`)}</Badge>
        {entry.generated_by && <Badge tone="info">{entry.generated_by === "llm" ? "LLM" : "Template"}</Badge>}
        {entry.group && <Badge tone="info">{entry.group}</Badge>}
      </span>
    </summary>
    <div className="verification-row-detail">
      <p>{entry.covered_property}</p>
      <dl><div><dt>{t("verificationWorkspace.rule")}</dt><dd>{entry.rule_id ?? t("verificationWorkspace.notReported")}</dd></div>
        <div><dt>{t("verificationWorkspace.result")}</dt><dd><code>{entry.status}</code></dd></div>
        <div><dt>{t("verificationWorkspace.strategy")}</dt><dd>{entry.strategy}</dd></div></dl>
      {entry.validated_red_green && <Badge tone="success">RED → GREEN</Badge>}
      {entry.summary && <details className="verification-message"><summary>{t("verificationWorkspace.fullMessage")}</summary><pre>{entry.summary}</pre></details>}
      {paths.length ? <div className="verification-files"><p>{t("verificationWorkspace.referencedFiles")}</p>
        {paths.map((path) => <Button key={path} variant="secondary" onClick={() => setSource(source === path ? null : path)}><CodeIcon /> {path}</Button>)}
        {source && <SourcePreview projectId={projectId} auditId={auditId} commit={baseline} path={source} />}
      </div> : <p className="verification-muted">{t("verificationWorkspace.noReferences")}</p>}
    </div>
  </details>
}

interface Props {
  projectId: number
  auditId: number
  baseline: string | null
  branch: string | null
  targetCommit: string
  onTargetChange: (commit: string) => void
  suiteScope: string
  onSuiteScopeChange: (scope: string) => void
  suite: VerificationSuitePage | null
  execution: VerificationSuitePage | null
  available: boolean
  enabled: boolean
  busy: boolean
  action: SuiteAction | null
  downloading: boolean
  error: string | null
  reconnecting: boolean
  create: () => void
  execute: () => void
  download: () => void
}

export function VerificationWorkspace(props: Props) {
  const { t } = useTranslation("projects")
  const [filter, setFilter] = useState("all")
  const targetValid = /^[a-f0-9]{40}$/i.test(props.targetCommit)
  const entries = props.execution?.verifications ?? []
  const counts = { all: entries.length, passed: 0, violation: 0, error: 0, other: 0 }
  for (const entry of entries) counts[verificationOutcome(entry.status)] += 1
  const filtered = entries.filter((entry) => filter === "all" || verificationOutcome(entry.status) === filter)
  return <div className="verification-workspace">
    <Card layout="stack" gap="md" align="stretch" className="verification-workspace-card">
      <header className="verification-heading"><ListIcon /><div><h3>{t("verificationWorkspace.suiteTitle")}</h3><p>{t("verificationWorkspace.suiteDescription")}</p></div>
        <Badge tone={props.available ? "success" : "info"}>{props.busy && props.action === "create" ? t("verificationWorkspace.creating") : props.available ? t("verificationWorkspace.available") : t("verificationWorkspace.noSuite")}</Badge></header>
      <dl className="verification-metadata"><div><dt>{t("verificationWorkspace.baseline")}</dt><dd><code>{props.baseline ?? t("verificationWorkspace.notReported")}</code></dd></div>
        <div><dt>{t("verificationWorkspace.checks")}</dt><dd>{props.suite ? props.suite.verifications.length : "—"}</dd></div>
        {!!props.suite?.groups?.length && <div><dt>{t("verificationWorkspace.groups")}</dt><dd>{props.suite.groups.map((group) => `${group.name} (${group.count})`).join(", ")}</dd></div>}</dl>
      {!props.available && <p className="verification-muted">{t("verificationWorkspace.createFirst")}</p>}
      <div className="verification-actions"><Button variant="primary" disabled={!props.enabled || props.busy} onClick={props.create}>{props.busy && props.action === "create" ? t("verificationWorkspace.creating") : t("verificationWorkspace.create")}</Button>
        <Button variant="secondary" disabled={!props.available || props.busy || props.downloading} onClick={props.download}>{props.downloading ? t("verificationWorkspace.downloading") : t("verificationWorkspace.download")}</Button></div>
      {!!props.suite?.limitations.length && <details><summary>{t("verificationWorkspace.limitations")} ({props.suite.limitations.length})</summary><ul className="verification-limitations">{props.suite.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
    </Card>

    <Card layout="stack" gap="md" align="stretch" className="verification-workspace-card">
      <header className="verification-heading"><ShieldIcon /><div><h3>{t("verificationWorkspace.runTitle")}</h3><p>{t("verificationWorkspace.runDescription")}</p></div></header>
      <CommitAncestorSelector projectId={props.projectId} auditId={props.auditId} disabled={props.busy}
        selected={props.targetCommit.toLowerCase()} onSelect={props.onTargetChange} />
      {props.baseline && <div className="verification-actions"><Button variant="secondary" disabled={props.busy} onClick={() => props.onTargetChange(props.baseline!)}>{t("verificationWorkspace.useBaseline")}</Button></div>}
      {props.targetCommit && <p className="verification-muted">{t("verificationWorkspace.targetCommit")}: <code>{props.targetCommit}</code></p>}
      <div className="verification-scope">
        <FilterTabs label={t("verificationWorkspace.scopeLabel")} value={props.suiteScope} onChange={props.onSuiteScopeChange}
          options={(props.suite?.groups?.length ? [{ id: "all", count: props.suite.verifications.length, label: t("verificationWorkspace.scopeAll") },
                                                ...props.suite.groups.map((group) => ({ id: group.name, count: group.count, label: group.name }))]
                    : [{ id: "all", count: props.suite?.verifications.length ?? 0, label: t("verificationWorkspace.scopeAll") }])} />
      </div>
      <p className="verification-muted">{t("verificationWorkspace.commitExecution")}</p>
      <div className="verification-actions"><Button variant="primary" disabled={!props.enabled || !props.available || props.busy || !targetValid} onClick={props.execute}>{props.busy && props.action === "execute" ? t("verificationWorkspace.running") : t("verificationWorkspace.execute")}</Button>
        {props.busy && <Spinner />}</div>
    </Card>

    {props.error && <p role="alert">{props.error}</p>}
    {props.reconnecting && <p role="status">{t("verificationWorkspace.reconnecting")}</p>}

    <Card layout="stack" gap="md" align="stretch" className="verification-workspace-card">
      <header className="verification-heading"><CodeIcon /><div><h3>{t("verificationWorkspace.resultsTitle")}</h3><p>{t("verificationWorkspace.passedExplanation")}</p></div>
        {props.execution && <Badge tone="info">{props.execution.validation_status}</Badge>}</header>
      {!props.execution ? <p className="verification-empty">{t("verificationWorkspace.noRuns")}</p> : <>
        <p className="verification-muted">{t("verificationWorkspace.latestRun")} · {t("verificationWorkspace.auditRun")}: <code>{props.execution.run_id}</code>
          {props.execution.attempt_id && <> · {t("verificationWorkspace.attempt")}: <code>{props.execution.attempt_id}</code></>}
          {" · "}{t("verificationWorkspace.effectiveCommit")}: <code>{props.execution.checkout_commit ?? t("verificationWorkspace.notReported")}</code>
          {" · "}{t("verificationWorkspace.targetCommit")}: <code>{props.execution.target_commit ?? t("verificationWorkspace.notReported")}</code>
          {props.execution.suite_id && <> · {t("verificationWorkspace.suiteTitle")}: <code>{props.execution.suite_id}</code></>}
          {props.execution.suite_sha256 && <> · SHA-256: <code>{props.execution.suite_sha256}</code></>}</p>
        <FilterTabs label={t("verificationWorkspace.filterLabel")} value={filter} onChange={setFilter}
          options={(["all", "passed", "violation", "error", "other"] as const).map((id) => ({ id, count: counts[id], label: counts[id] ? t(`verificationWorkspace.${id}`) : `${t(`verificationWorkspace.${id}`)} (0)` }))} />
        <div className="verification-rows">{filtered.map((entry) => <VerificationRow key={entry.verification_id} entry={entry} projectId={props.projectId} auditId={props.auditId} baseline={props.baseline ?? ""} />)}</div>
        {!filtered.length && <p className="verification-empty">{t("verificationWorkspace.noMatches")}</p>}
        {!!props.execution.limitations.length && <details><summary>{t("verificationWorkspace.limitations")} ({props.execution.limitations.length})</summary><ul className="verification-limitations">{props.execution.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
      </>}
    </Card>
  </div>
}

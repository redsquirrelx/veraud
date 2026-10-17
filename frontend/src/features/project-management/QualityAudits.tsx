import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Badge, Button, Card } from "../../shared/ui-kit/index.ts"
import { downloadQualityAuditReport, getQualityAuditReport, listQualityAudits, startQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import "./QualityAudits.css"

const sections = [
  ["identification", "1. Identificación"],
  ["executive_summary", "2. Resumen ejecutivo"],
  ["objectives_and_scope", "3. Objetivos y alcance"],
  ["methodology_and_criteria", "4. Metodología y criterios"],
  ["software_description", "5. Descripción del software"],
  ["quality_results", "6. Resultados de calidad"],
  ["consolidated_risks", "7. Riesgos consolidados"],
  ["general_conclusions", "8. Conclusiones generales"],
  ["recommendations_and_improvement_plan", "9. Recomendaciones y plan de mejora"],
  ["annexes_and_traceability", "10. Anexos y trazabilidad"],
] as const

const labels: Record<string, string> = {
  objective: "Objetivo", evaluated_attributes: "Atributos evaluados", principal_results: "Resultados principales",
  conclusion: "Conclusión", findings: "Hallazgos", total: "Total", by_verification: "Por verificación",
  verified: "Verificados", inconclusive: "Inconclusos", discarded: "Descartados",
  status: "Estado", limitations: "Limitaciones", source_refs: "Referencias de origen",
  title: "Título", project_name: "Proyecto", revisions: "Revisiones", executed_at: "Fecha de ejecución",
}

/** Render the canonical report as data, preserving statements and traceability. */
function ReportValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="label">No registrado</span>
  if (Array.isArray(value)) return value.length === 0 ? <span className="label">Sin registros</span>
    : <ul>{value.map((item, index) => <li key={index}><ReportValue value={item} /></li>)}</ul>
  if (typeof value === "object") {
    const record = value as Record<string, unknown>
    if (typeof record.text === "string") return <>
      <p>{record.text}</p>
      {Array.isArray(record.source_refs) && record.source_refs.length > 0 && <details>
        <summary>Referencias de origen ({record.source_refs.length})</summary>
        <pre>{JSON.stringify(record.source_refs, null, 2)}</pre>
      </details>}
    </>
    return <dl>{Object.entries(record).map(([key, child]) => <div key={key}>
      <dt>{labels[key] ?? key.replaceAll("_", " ")}</dt>
      <dd><ReportValue value={child} /></dd>
    </div>)}</dl>
  }
  return <span>{String(value)}</span>
}

function reportRunId(document: Record<string, unknown>): string | null {
  const identification = document.identification
  if (!identification || typeof identification !== "object") return null
  const id = (identification as Record<string, unknown>).audit_id
  return typeof id === "string" && id.length > 0 ? id : null
}

function AuditRunId({ projectId, audit }: { projectId: number, audit: QualityAuditSummary }) {
  const [runId, setRunId] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (audit.runId || !audit.reportAvailable) return
    let alive = true
    getQualityAuditReport(projectId, audit.id).then(
      (document) => { if (alive) setRunId(reportRunId(document)) },
      () => { if (alive) setRunId(null) },
    ).finally(() => { if (alive) setLoaded(true) })
    return () => { alive = false }
  }, [projectId, audit.id, audit.reportAvailable, audit.runId])

  const id = audit.runId ?? runId
  const serverUrl = (import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")
  const pending = audit.reportAvailable && !loaded ? "Cargando…"
    : ["Waiting", "Running"].includes(audit.executionStatus) ? "Inicializando…" : "No disponible"
  return <p className="audit-run-id">Run ID: {id
    ? <><code>{id}</code>{" · "}<a href={`${serverUrl}/blackboard?run_id=${encodeURIComponent(id)}`} target="_blank" rel="noreferrer">Ver Blackboard</a></>
    : <span>{pending}</span>}</p>
}

export function QualityAudits({ projectId, branch, commitHash, canRun }: {
  projectId: number, branch: string | null, commitHash: string | null, canRun: boolean,
}) {
  const [selected, setSelected] = useState(true)
  const [audits, setAudits] = useState<QualityAuditSummary[]>([])
  const [starting, setStarting] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState("")
  const [report, setReport] = useState<{ id: number, document: Record<string, unknown> } | null>(null)
  const [loadingReport, setLoadingReport] = useState<number | null>(null)
  const [downloading, setDownloading] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      try {
        const rows = await listQualityAudits(projectId)
        if (!alive) return
        setAudits(rows)
        if (rows.some((row) => ["Waiting", "Running"].includes(row.executionStatus))) {
          timer = setTimeout(() => void load(), 3000)
        }
      } catch (cause) {
        if (alive) {
          setError(cause instanceof Error ? cause.message : "Could not load audits")
          timer = setTimeout(() => void load(), 5000)
        }
      }
    }
    void load()
    return () => { alive = false; clearTimeout(timer) }
  }, [projectId, refresh])

  const running = audits.some((row) => ["Waiting", "Running"].includes(row.executionStatus))

  async function start() {
    if (!branch || !commitHash || !selected || starting) return
    setStarting(true)
    setError("")
    try {
      await startQualityAudit(projectId, branch, commitHash, ["maintainability"])
      setRefresh((value) => value + 1)
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start audit") }
    finally { setStarting(false) }
  }

  async function view(id: number) {
    setLoadingReport(id)
    setError("")
    try { setReport({ id, document: await getQualityAuditReport(projectId, id) }) }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load report") }
    finally { setLoadingReport(null) }
  }

  async function download(id: number) {
    setDownloading(id)
    setError("")
    try { await downloadQualityAuditReport(projectId, id) }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not download report") }
    finally { setDownloading(null) }
  }

  return <div className="quality-audits">
    <Card>
      <h2>Auditoría de calidad</h2>
      <p>Selecciona los atributos de calidad para la versión {commitHash?.slice(0, 7) ?? "pendiente"}.</p>
      <label className="quality-attribute"><input type="checkbox" checked={selected} onChange={(event) => setSelected(event.target.checked)} /> Mantenibilidad</label>
      <div className="audit-button-row">
        <Button disabled={!canRun || !selected || starting || running} onClick={() => void start()}>{starting ? "Iniciando…" : "Iniciar auditoría"}</Button>
        <Button onClick={() => setRefresh((value) => value + 1)}>Actualizar</Button>
        <Link to="/settings">Configurar agentes</Link>
      </div>
      {running && <p role="status">Auditoría en curso. Los resultados se conservarán aunque la evaluación sea parcial.</p>}
      {error && <p role="alert">{error}</p>}
    </Card>
    <Card>
      <h3>Auditorías del proyecto</h3>
      {audits.length === 0 && <p>No hay auditorías registradas.</p>}
      {audits.map((audit) => <article className="quality-audit-run" key={audit.id}>
        <h4>Mantenibilidad · #{audit.id} · {audit.branch} @ {audit.commitHash?.slice(0, 7)}</h4>
        <AuditRunId key={`${projectId}-${audit.id}`} projectId={projectId} audit={audit} />
        <Badge tone={audit.auditStatus === "partial" || audit.executionStatus === "Failed" || audit.auditStatus === "failed" ? "warning" : "info"}>
          {audit.auditStatus === "partial" ? "Evaluación parcial" : audit.auditStatus === "completed" ? "Evaluación completada" : audit.auditStatus === "failed" ? "Evaluación fallida" : audit.executionStatus}
        </Badge>
        <p className="label">{new Date(audit.createdAt).toLocaleString()}</p>
        {audit.error && <p role="alert">{audit.error}</p>}
        {audit.reportAvailable && <div className="audit-button-row">
          <Button disabled={loadingReport !== null} onClick={() => void view(audit.id)}>{loadingReport === audit.id ? "Cargando…" : "Ver informe"}</Button>
          <Button disabled={downloading !== null} onClick={() => void download(audit.id)}>{downloading === audit.id ? "Descargando…" : "Descargar informe Word"}</Button>
        </div>}
      </article>)}
    </Card>
    {report && <Card>
      <h2>Informe de auditoría · #{report.id}</h2>
      {reportRunId(report.document) && <p>Run ID: <code>{reportRunId(report.document)}</code></p>}
      <p>Informe original generado a partir del Blackboard de esta ejecución.</p>
      <div className="quality-report">{sections.map(([key, title]) => <details key={`${report.id}-${key}`} open={key === "executive_summary"}>
        <summary>{title}</summary>
        <ReportValue value={report.document[key]} />
      </details>)}</div>
    </Card>}
  </div>
}

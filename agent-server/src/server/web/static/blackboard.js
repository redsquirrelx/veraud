"use strict";

(() => {
    const runId = new URLSearchParams(window.location.search).get("run_id");
    if (!runId || !runId.trim()) return;

    const element = (id) => document.getElementById(id);
    const connection = element("connection");
    const reportButton = element("download-report");
    const reportStatus = element("report-status");
    let auditAvailable = false;
    let downloadingReport = false;
    const labels = {
        queued: "En cola", running: "En ejecución", completed: "Finalizada",
        partial: "Finalizada con resultados parciales", failed: "Fallida", cancelled: "Cancelada",
    };
    const active = new Set(["queued", "running"]);
    // Keep existing nodes so open details and selection survive a refresh.
    const records = new Map();
    const failureNodes = new Map();

    function renderFailures(audit) {
        const incomplete = new Set(["partial", "failed", "timeout", "skipped", "cancelled"]);
        const issues = audit.execution_issues || [];
        const current = new Set(issues.map(issue => issue.invocation_id));
        for (const [key, node] of failureNodes) {
            if (!current.has(key)) { node.details.remove(); failureNodes.delete(key); }
        }
        for (const issue of issues) {
            let node = failureNodes.get(issue.invocation_id);
            if (!node) {
                const details = document.createElement("details");
                const summary = document.createElement("summary");
                const content = document.createElement("pre");
                details.append(summary, content);
                element("execution-issues").append(details);
                node = {details, summary, content};
                failureNodes.set(issue.invocation_id, node);
            }
            const status = {skipped: "No ejecutado", partial: "Investigación incompleta", failed: "Falló",
                timeout: "Tiempo agotado", cancelled: "Cancelado"}[issue.status] || "Incidencia";
            node.summary.textContent = `${issue.agent_id} · ${status}: ${issue.explanation}`;
            node.content.textContent = [
                `Invocación: ${issue.invocation_id} · Motivo: ${issue.termination_reason || "No consta"}`,
                ...(issue.incidents || []), ...(issue.diagnostics || []),
                `Registros de origen: ${(issue.source_record_ids || []).join(", ")}`,
            ].join("\n");
        }
        element("execution-issues").hidden = !issues.length;
        const lines = [];
        if (audit.error) lines.push(`Motivo de la ejecución: ${audit.error}`);
        if (issues.length) {
            lines.push(`${issues.length} ejecuciones incompletas o fallidas. Consulta el detalle por agente.`);
            const incidents = [...new Set(issues.flatMap(issue => issue.incidents || []))];
            lines.push(...incidents);
        }
        if (!lines.length && incomplete.has(audit.status)) {
            lines.push(audit.status === "cancelled" ? "La auditoría fue cancelada."
                : "La ejecución terminó sin completar la evaluación. No se publicó una causa específica.");
        }
        element("audit-error").textContent = lines.join("\n\n");
        element("audit-error").hidden = !lines.length;
    }

    reportButton.addEventListener("click", async () => {
        if (!auditAvailable || downloadingReport) return;
        downloadingReport = true;
        reportButton.disabled = true;
        reportButton.textContent = "Generando informe…";
        reportStatus.textContent = "Preparando el documento Word con los registros publicados…";
        try {
            const response = await fetch(`/api/audits/${encodeURIComponent(runId)}/report.docx`, {
                cache: "no-store", signal: AbortSignal.timeout(120000),
            });
            if (!response.ok) {
                if (response.status === 404) {
                    auditAvailable = false;
                    reportStatus.textContent = "Auditoría no encontrada. Comprueba el run_id o actualiza la página.";
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = "informe-auditoria.docx";
            document.body.append(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            reportStatus.textContent = "Descarga del informe iniciada.";
        } catch {
            reportStatus.textContent = "No se pudo descargar el informe. Inténtalo de nuevo.";
        } finally {
            downloadingReport = false;
            reportButton.disabled = !auditAvailable;
            reportButton.textContent = "Descargar informe Word";
        }
    });

    function renderRecords(kind, items) {
        const container = element(kind);
        element(`${kind}-count`).textContent = items.length;
        if (!items.length && !container.firstChild) {
            const empty = document.createElement("p");
            empty.className = "empty";
            empty.textContent = "Todavía no hay registros publicados.";
            container.append(empty);
        }
        for (const record of items) {
            const key = `${kind}:${record.id}`;
            const serialized = JSON.stringify(record, null, 2);
            const existing = records.get(key);
            if (existing) {
                if (existing.content.textContent !== serialized) existing.content.textContent = serialized;
                continue;
            }
            container.querySelector(".empty")?.remove();
            const details = document.createElement("details");
            const summary = document.createElement("summary");
            summary.textContent = `${record.title || record.source || record.objective || record.id} — ${record.agent_id}`;
            const provenance = document.createElement("p");
            provenance.textContent = `ID: ${record.id} · Invocación: ${record.invocation_id}`;
            const content = document.createElement("pre");
            content.textContent = serialized;
            details.append(summary, provenance, content);
            container.append(details);
            records.set(key, {content});
        }
    }

    async function refresh() {
        let retry = true;
        try {
            const response = await fetch(`/api/audits/${encodeURIComponent(runId)}`, {
                cache: "no-store", signal: AbortSignal.timeout(10000),
            });
            if (response.status === 404) {
                auditAvailable = false;
                reportButton.disabled = true;
                connection.textContent = "Auditoría no encontrada en este servidor. Comprueba el run_id; los datos en memoria se pierden al reiniciar.";
                retry = false;
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const audit = await response.json();
            auditAvailable = true;
            reportButton.disabled = downloadingReport;
            element("report-hint").textContent = active.has(audit.status)
                ? "La auditoría sigue en curso. El informe reflejará los resultados parciales publicados hasta su generación."
                : "El informe incluirá los resultados publicados y sus limitaciones, incluso si la auditoría terminó parcial o fallida.";
            element("audit-status").textContent = labels[audit.status] || audit.status;
            element("audit-meta").textContent = `Run: ${audit.run_id} · Invocación raíz: ${audit.invocation_id} · Creada: ${audit.created_at}`;
            renderFailures(audit);
            const waiting = audit.waiting || [];
            element("audit-waits").hidden = !waiting.length;
            element("audit-waits").textContent = waiting.map((wait) => {
                const seconds = wait.retry_after_seconds == null ? "" : ` · ${Math.ceil(wait.retry_after_seconds)} s restantes`;
                return `En espera: ${wait.agent_id || "agente"} · ${wait.reason}${seconds} · origen: ${wait.source || "admisión local"}`;
            }).join("\n");
            const activity = audit.activity || [];
            element("audit-activity").hidden = !activity.length;
            element("audit-activity").textContent = activity.map((item) =>
                `${item.agent_id || "agente"} · ${item.stage} · ${Math.floor(item.elapsed_seconds)} s · ${item.status === "cancellation_pending" ? "cancelación pendiente" : "en curso"}`
            ).join("\n") + (audit.last_progress_at ? `\nÚltimo avance: ${new Date(audit.last_progress_at).toLocaleTimeString()}` : "")
                + (audit.wall_seconds_remaining != null ? ` · Límite absoluto: ${Math.ceil(audit.wall_seconds_remaining)} s restantes` : "");
            for (const kind of ["evidence", "findings", "assessments"]) renderRecords(kind, audit[kind]);
            element("audit").hidden = false;
            element("updated-at").textContent = `Última actualización: ${new Date().toLocaleTimeString()}`;
            retry = active.has(audit.status);
            connection.textContent = retry
                ? "Actualización automática cada 2 segundos."
                : "Ejecución terminada. Se muestran los registros publicados.";
        } catch {
            connection.textContent = "No se pudo actualizar. Se conservan los datos anteriores y se reintentará en 2 segundos.";
        } finally {
            // Schedule after completion to avoid overlapping requests.
            if (retry) window.setTimeout(refresh, 2000);
        }
    }

    connection.textContent = "Consultando auditoría…";
    refresh();
})();

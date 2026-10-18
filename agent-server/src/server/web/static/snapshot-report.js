"use strict";

(() => {
    const element = id => document.getElementById(id);
    const form = element("snapshot-report-form");
    const button = element("generate-snapshot-report");
    const status = element("snapshot-report-status");
    let generating = false;
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (generating) return;
        const file = element("snapshot-file").files[0];
        if (!file) {
            status.textContent = "Selecciona un archivo JSON del Blackboard.";
            return;
        }
        generating = true;
        button.disabled = true;
        status.textContent = "Generando informe desde el análisis guardado…";
        element("snapshot-generation-json").hidden = true;
        try {
            let snapshot;
            try { snapshot = JSON.parse((await file.text()).replace(/^\uFEFF/, "")); }
            catch { throw new Error("El archivo no contiene un JSON válido."); }
            if (!snapshot || typeof snapshot.run_id !== "string" || !snapshot.run_id.trim()
                || !["evidence", "findings", "assessments"].every(key => Array.isArray(snapshot[key]))) {
                throw new Error("Selecciona el análisis exportado del Blackboard: debe incluir run_id, evidence, findings y assessments.");
            }
            const format = element("snapshot-format").value === "json" ? "json" : "docx";
            const response = await fetch(`/api/audits/reports/from-snapshot${format === "docx" ? ".docx" : ""}`, {
                method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(snapshot),
                cache: "no-store", signal: AbortSignal.timeout(120000),
            });
            if (!response.ok) {
                throw new Error(response.status === 422
                    ? "El JSON no es un snapshot válido: revisa los registros y que todos pertenezcan al mismo run_id."
                    : "No se pudo generar el informe. Inténtalo de nuevo.");
            }
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a");
            link.href = url;
            link.download = `informe-auditoria.${format}`;
            document.body.append(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            status.textContent = "Informe generado. Descarga iniciada.";
            const generationId = response.headers?.get("X-Report-Generation-ID");
            if (generationId) {
                const receipt = element("snapshot-generation-json");
                receipt.href = `/api/audits/${encodeURIComponent(snapshot.run_id)}/report-generations/${encodeURIComponent(generationId)}`;
                receipt.download = `informe-${generationId}.json`;
                receipt.hidden = false;
                status.textContent += ` Generación: ${generationId}.`;
            }
        } catch (error) {
            status.textContent = error.message || "No se pudo generar el informe. Inténtalo de nuevo.";
        } finally {
            generating = false;
            button.disabled = false;
        }
    });
})();

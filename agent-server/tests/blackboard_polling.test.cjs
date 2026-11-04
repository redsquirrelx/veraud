const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {resolve} = require("node:path");
const {runInNewContext} = require("node:vm");

const source = readFileSync(resolve(__dirname, "../src/server/web/static/blackboard.js"), "utf8");

class Element {
    children = [];
    textContent = "";
    hidden = true;
    disabled = true;
    listeners = new Map();
    addEventListener(name, callback) { this.listeners.set(name, callback); }
    click() { this.clicked = true; return this.listeners.get("click")?.(); }
    append(...nodes) {
        for (const node of nodes) node.parent = this;
        this.children.push(...nodes);
    }
    get firstChild() { return this.children[0]; }
    querySelector() { return this.children.find(node => node.className === "empty"); }
    remove() { this.parent.children = this.parent.children.filter(node => node !== this); }
}

async function viewer(responses, search = "?run_id=audit") {
    const elements = new Map();
    const timers = [];
    const calls = [];
    const downloads = [];
    const revoked = [];
    const body = new Element();
    runInNewContext(source, {
        URLSearchParams, AbortSignal, Blob,
        URL: {
            createObjectURL(blob) { downloads.push(blob); return "blob:report"; },
            revokeObjectURL(url) { revoked.push(url); },
        },
        document: {
            body,
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, new Element());
                return elements.get(id);
            },
            createElement: () => new Element(),
        },
        window: {location: {search}, setTimeout: (callback, delay) => timers.push({callback, delay})},
        fetch: async (url, options) => {
            calls.push({url, options});
            const response = responses.shift();
            if (response instanceof Error) throw response;
            return response;
        },
    });
    await new Promise(setImmediate);
    return {elements, timers, calls, downloads, revoked, body};
}

const record = {id: "e1", agent_id: "investigator", invocation_id: "child", source: "<img src=x onerror=alert(1)>"};
function ok(status, evidence = [record]) {
    return {ok: true, status: 200, json: async () => ({
        run_id: "audit", invocation_id: "root", created_at: "now", status,
        evidence, findings: [], assessments: [], error: status === "failed" ? "Failure" : null,
    })};
}

test("polls every two seconds, preserves open details and stops on terminal state", async () => {
    const view = await viewer([ok("running"), ok("completed")]);
    assert.equal(view.calls[0].url, "/api/audits/audit");
    assert.equal(view.calls[0].options.cache, "no-store");
    assert.equal(view.timers.length, 1);
    assert.equal(view.timers[0].delay, 2000);
    const details = view.elements.get("evidence").firstChild;
    details.open = true;
    assert.match(details.firstChild.textContent, /<img/); // Rendered as text, never HTML.
    await view.timers.shift().callback();
    assert.equal(view.elements.get("evidence").firstChild, details);
    assert.equal(details.open, true);
    assert.equal(view.timers.length, 0);
    assert.equal(view.elements.get("audit-status").textContent, "Finalizada");
});

test("shows in-flight work and pending cancellation without treating polling as progress", async () => {
    const response = ok("running");
    const data = await response.json();
    data.activity = [{agent_id: "responsibility", stage: "review_findings:provider_request", elapsed_seconds: 7.8,
        status: "cancellation_pending"}];
    data.last_progress_at = "2026-10-17T10:00:00Z";
    data.wall_seconds_remaining = 42.3;
    response.json = async () => data;
    const view = await viewer([response, ok("completed")]);
    const activity = view.elements.get("audit-activity");
    assert.equal(activity.hidden, false);
    assert.match(activity.textContent, /responsibility.*review_findings:provider_request.*7 s.*cancelación pendiente/);
    assert.match(activity.textContent, /Último avance:/);
    assert.match(activity.textContent, /Límite absoluto: 43 s restantes/);
    await view.timers.shift().callback();
    assert.equal(activity.hidden, true);
});

test("retries connection failures retaining partial data, then displays failure", async () => {
    const view = await viewer([ok("running"), new Error("offline"), ok("failed")]);
    await view.timers.shift().callback();
    assert.equal(view.elements.get("evidence").children.length, 1);
    assert.match(view.elements.get("connection").textContent, /reintentará/);
    await view.timers.shift().callback();
    assert.equal(view.elements.get("audit-error").hidden, false);
    assert.equal(view.timers.length, 0);
});

test("missing audit stops polling; missing run_id sends no request", async () => {
    const missing = await viewer([{status: 404}]);
    assert.equal(missing.timers.length, 0);
    assert.match(missing.elements.get("connection").textContent, /no encontrada/);
    const blank = await viewer([], "");
    assert.equal(blank.calls.length, 0);
});

test("shows provider wait origin and clears the notice after recovery", async () => {
    const response = ok("running");
    const original = response.json;
    response.json = async () => ({...await original(), waiting: [{
        agent_id: "architecture_boundary", reason: "provider_retry_after",
        retry_after_seconds: 69273, source: "google.rpc.RetryInfo.retryDelay",
    }]});
    const view = await viewer([response, ok("completed")]);
    const notice = view.elements.get("audit-waits");
    assert.equal(notice.hidden, false);
    assert.match(notice.textContent, /architecture_boundary.*69273 s.*google.rpc.RetryInfo.retryDelay/);
    await view.timers.shift().callback();
    assert.equal(notice.hidden, true);
});

test("explains failed child executions in partial audits with their original diagnostics", async () => {
    const response = ok("partial");
    const original = response.json;
    response.json = async () => ({...await original(), execution_issues: [{
        agent_id: "architecture_boundary", invocation_id: "boundary-1", termination_reason: "provider_retry_wait_limit",
        explanation: "El proveedor solicitó una espera superior al límite automático permitido.",
        incidents: ["Incidencia del proveedor."], source_record_ids: ["assessment"],
        diagnostics: ["requested_wait_seconds=44378 max_wait_seconds=120", "<img src=x onerror=alert(1)>"],
    }, {agent_id: "dependency_impact", invocation_id: "dependency-1", termination_reason: "timeout",
        explanation: "Tiempo de ejecución agotado.", diagnostics: [], incidents: [], source_record_ids: ["assessment"]}]});
    const view = await viewer([response]);
    const notice = view.elements.get("audit-error");
    assert.equal(notice.hidden, false);
    assert.match(notice.textContent, /2 ejecuciones/);
    assert.doesNotMatch(notice.textContent, /44378|<img/); // Technical details stay collapsed.
    const [boundary, dependency] = view.elements.get("execution-issues").children;
    assert.match(boundary.firstChild.textContent, /architecture_boundary.*espera superior/);
    assert.match(boundary.children[1].textContent, /44378.*120/);
    assert.match(boundary.children[1].textContent, /<img/); // Literal text, never HTML.
    assert.match(dependency.firstChild.textContent, /dependency_impact.*Tiempo de ejecución agotado/);
});

test("preserves open failure details during polling and clears obsolete failures", async () => {
    const failed = ok("running");
    const original = failed.json;
    failed.json = async () => ({...await original(), execution_issues: [{
        agent_id: "investigator", invocation_id: "child", explanation: "Sin presupuesto compartido.",
        incidents: ["Sin presupuesto compartido."], diagnostics: [], source_record_ids: ["e1"],
    }]});
    const view = await viewer([failed, failed, ok("completed", [])]);
    const notice = view.elements.get("audit-error");
    assert.match(notice.textContent, /presupuesto compartido/);
    const details = view.elements.get("execution-issues").firstChild;
    details.open = true;
    await view.timers.shift().callback();
    assert.equal(view.elements.get("execution-issues").firstChild, details);
    assert.equal(details.open, true);
    await view.timers.shift().callback();
    assert.equal(notice.hidden, true);
    assert.equal(view.elements.get("execution-issues").children.length, 0);
});

test("failed execution without a diagnostic explicitly reports the missing cause", async () => {
    const response = ok("failed");
    const original = response.json;
    response.json = async () => ({...await original(), error: null});
    const view = await viewer([response]);
    assert.equal(view.elements.get("audit-error").hidden, false);
    assert.match(view.elements.get("audit-error").textContent, /No se publicó una causa específica/);
});

test("downloads DOCX for the displayed audit and releases the temporary URL", async () => {
    const blob = {type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"};
    const view = await viewer([ok("completed"), {ok: true, blob: async () => blob}], "?run_id=audit%2Fone");
    const button = view.elements.get("download-report");
    assert.equal(button.disabled, false);
    await button.click();
    assert.equal(view.calls[1].url, "/api/audits/audit%2Fone/report.docx");
    assert.equal(view.calls[1].options.cache, "no-store");
    assert.deepEqual(view.downloads, [blob]);
    assert.equal(view.body.children.length, 0);
    assert.equal(button.disabled, false);
    assert.match(view.elements.get("report-status").textContent, /iniciada/);
    await view.timers.shift().callback();
    assert.deepEqual(view.revoked, ["blob:report"]);
});

test("prevents duplicate downloads while allowing polling to continue", async () => {
    let finish;
    const blob = new Promise(resolve => { finish = resolve; });
    const view = await viewer([ok("running"), {ok: true, blob: async () => blob}, ok("completed")]);
    const button = view.elements.get("download-report");
    assert.match(view.elements.get("report-hint").textContent, /parciales/);
    const pending = button.click();
    assert.equal(button.disabled, true);
    await button.click();
    assert.equal(view.calls.length, 2);
    await view.timers.shift().callback();
    assert.equal(button.disabled, true);
    finish({});
    await pending;
    assert.equal(button.disabled, false);
});

test("download errors are visible and retryable; missing audits disable the button", async () => {
    const view = await viewer([ok("completed"), {ok: false, status: 500}, {ok: false, status: 404}]);
    const button = view.elements.get("download-report");
    await button.click();
    assert.match(view.elements.get("report-status").textContent, /Inténtalo de nuevo/);
    assert.equal(button.disabled, false);
    await button.click();
    assert.match(view.elements.get("report-status").textContent, /no encontrada/);
    assert.equal(button.disabled, true);
    const missing = await viewer([{status: 404}]);
    assert.equal(missing.elements.get("download-report").disabled, true);
});

test("downloads a fresh complete snapshot only after termination, preserving nested knowledge", async () => {
    const final = ok("partial");
    const snapshot = await final.json();
    snapshot.assessments = [{id: "manager", details: {report: {assessments: [{invocations: [{result: {
        hypotheses: [{status: "inconclusive"}], validation_issues: ["missing caller inspection"],
    }}]}]}}}];
    final.json = async () => snapshot;
    const view = await viewer([ok("running"), ok("partial"), final]);
    const button = view.elements.get("download-analysis");
    assert.equal(button.disabled, true);
    await button.click();
    assert.equal(view.calls.length, 1);
    await view.timers.shift().callback();
    assert.equal(button.disabled, false);
    await button.click();
    assert.equal(view.calls[2].url, "/api/audits/audit");
    assert.deepEqual(JSON.parse(await view.downloads[0].text()), snapshot);
    assert.equal(view.body.children.length, 0);
    await view.timers.shift().callback();
    assert.deepEqual(view.revoked, ["blob:report"]);
});

test("snapshot download failure remains retryable without downloading stale cached data", async () => {
    const view = await viewer([ok("failed"), {ok: false, status: 404}]);
    await view.elements.get("download-analysis").click();
    assert.equal(view.downloads.length, 0);
    assert.match(view.elements.get("analysis-status").textContent, /No se pudo/);
    assert.equal(view.elements.get("download-analysis").disabled, false);
});

const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {resolve} = require("node:path");
const {runInNewContext} = require("node:vm");

const source = readFileSync(resolve(__dirname, "../src/server/web/static/snapshot-report.js"), "utf8");
const snapshot = {run_id: "saved-run", evidence: [], findings: [], assessments: []};

function viewer(text, format = "docx", responses = []) {
    const elements = new Map();
    const calls = [], downloads = [], timers = [], revoked = [];
    const get = id => {
        if (!elements.has(id)) elements.set(id, {listeners: {}, textContent: "", disabled: false,
            addEventListener(event, listener) { this.listeners[event] = listener; }});
        return elements.get(id);
    };
    get("snapshot-file").files = text == null ? [] : [{text: async () => text}];
    get("snapshot-format").value = format;
    runInNewContext(source, {
        AbortSignal,
        document: {getElementById: get, body: {append(link) { downloads.push(link); }},
            createElement: () => ({click() {}, remove() {}})},
        URL: {createObjectURL(blob) { return blob; }, revokeObjectURL(url) { revoked.push(url); }},
        window: {setTimeout: callback => timers.push(callback)},
        fetch: async (url, options) => {
            calls.push({url, options});
            return responses.shift();
        },
    });
    const submit = () => get("snapshot-report-form").listeners.submit({preventDefault() {}});
    return {get, submit, calls, downloads, timers, revoked};
}

for (const format of ["docx", "json"]) {
    test(`generates ${format} from a JSON file without a run_id in the page URL`, async () => {
        const view = viewer("\uFEFF" + JSON.stringify(snapshot), format, [{ok: true, blob: async () => "file-bytes",
            headers: {get: () => "generation-1"}}]);
        await view.submit();
        assert.equal(view.calls[0].url, `/api/audits/reports/from-snapshot${format === "docx" ? ".docx" : ""}`);
        assert.equal(view.calls[0].options.method, "POST");
        assert.deepEqual(JSON.parse(view.calls[0].options.body), snapshot);
        assert.equal(view.downloads[0].download, `informe-auditoria.${format}`);
        assert.equal(view.get("generate-snapshot-report").disabled, false);
        assert.equal(view.get("snapshot-generation-json").hidden, false);
        assert.equal(view.get("snapshot-generation-json").href, "/api/audits/saved-run/report-generations/generation-1");
        view.timers[0]();
        assert.deepEqual(view.revoked, ["file-bytes"]);
    });
}

test("rejects invalid files locally and displays server validation failures without a download", async () => {
    for (const [input, message] of [[null, /Selecciona/], ["{", /JSON válido/],
        ['{"identification":{"audit_id":"audit"}}', /análisis exportado/]]) {
        const view = viewer(input);
        await view.submit();
        assert.equal(view.calls.length, 0);
        assert.match(view.get("snapshot-report-status").textContent, message);
    }
    const view = viewer(JSON.stringify(snapshot), "json", [{ok: false, status: 422}]);
    await view.submit();
    assert.equal(view.downloads.length, 0);
    assert.match(view.get("snapshot-report-status").textContent, /snapshot válido/);
    assert.equal(view.get("generate-snapshot-report").disabled, false);
});

test("prevents concurrent report generation", async () => {
    let finish;
    const pending = new Promise(resolve => { finish = resolve; });
    const view = viewer(JSON.stringify(snapshot), "docx", [
        {ok: true, blob: async () => pending}, {ok: true, blob: async () => "retry"},
    ]);
    const request = view.submit();
    await new Promise(setImmediate);
    await view.submit();
    assert.equal(view.calls.length, 1);
    assert.equal(view.get("generate-snapshot-report").disabled, true);
    finish("report");
    await request;
    assert.equal(view.get("generate-snapshot-report").disabled, false);
});

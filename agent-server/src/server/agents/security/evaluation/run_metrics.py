"""Corrida y métricas del módulo de seguridad sobre el benchmark etiquetado.

Uso (desde agent-server/):
    uv run python -m server.agents.security.evaluation.run_metrics --parte 1

No modifica agentes ni el repositorio: trabaja sobre una copia temporal del
benchmark. No invoca modelos (0 tokens).
"""

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from ..sast_scanner.agent import SASTScannerAgent
from ..sca_dependency.agent import SCADependencyAgent
from ..secret_scanner.agent import SecretScannerAgent
from ..security_verifier.agent import NOT_VERIFIED, PERSISTS, RESOLVED, SecurityVerifierAgent

BENCHMARK = Path(__file__).parent / "benchmark"

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:  # salida en texto plano si rich no está disponible
    console = None


# ----------------------------------------------------------------- salida
def title(text, subtitle=""):
    if console:
        console.print()
        console.print(Panel(f"[bold]{text}[/bold]" + (f"\n[dim]{subtitle}[/dim]" if subtitle else ""),
                            border_style="cyan", expand=False))
    else:
        print(f"\n=== {text} ===" + (f"\n{subtitle}" if subtitle else ""))


def table(caption, columns, rows):
    if console:
        t = Table(title=caption, box=box.ROUNDED, header_style="bold cyan", show_lines=True, title_justify="left",
                  min_width=len(caption) + 4 if caption else None)
        for name in columns:
            t.add_column(name, overflow="fold")
        for row in rows:
            t.add_row(*[str(cell) for cell in row])
        console.print(t)
    else:
        print(f"\n{caption}")
        print(" | ".join(columns))
        for row in rows:
            print(" | ".join(str(cell) for cell in row))


def status_label(status):
    colors = {PERSISTS: "red", RESOLVED: "green", NOT_VERIFIED: "yellow"}
    return f"[{colors[status]}]{status}[/{colors[status]}]" if console else status


def check(ok):
    return ("[green]✔[/green]" if ok else "[red]✘[/red]") if console else ("OK" if ok else "ERROR")


# ----------------------------------------------------------------- benchmark
def load_cases():
    return json.loads((BENCHMARK / "labels.json").read_text(encoding="utf-8"))["cases"]


def place(root: Path, case: dict, variant: str) -> Path:
    """Copia la variante indicada del caso a la copia de trabajo y devuelve su ruta."""
    target = root / case["id"] / case["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BENCHMARK / case["id"] / variant / case["file"], target)
    return target


SCANNERS = [("SAST (código)", SASTScannerAgent, "scan_path"),
            ("Secretos", SecretScannerAgent, "scan_path"),
            ("SCA (dependencias)", SCADependencyAgent, "scan_dependencies")]


def scan(root: Path, cases: list[dict]):
    """Ejecuta los tres escáneres de seguridad sobre cada caso.

    Devuelve ({caso: [Finding]}, {escáner: {"seconds", "findings"}}).
    """
    agents = [(name, cls(), method) for name, cls, method in SCANNERS]
    timing = {name: {"seconds": 0.0, "findings": 0} for name, _, _ in SCANNERS}
    found = {}
    for case in cases:
        folder = root / case["id"]
        findings = []
        for name, agent, method in agents:
            started = time.perf_counter()
            produced = getattr(agent, method)(str(folder))
            timing[name]["seconds"] += time.perf_counter() - started
            timing[name]["findings"] += len(produced)
            findings.extend(produced)
        for finding in findings:
            finding.file_path = Path(finding.file_path).relative_to(root).as_posix()
        found[case["id"]] = findings
    return found, timing


def outcome(case, findings):
    """Clasificación a nivel de caso contra la verdad de base."""
    if case["vulnerable"]:
        return "TP" if findings else "FN"
    return "FP" if findings else "TN"


OUTCOME_STYLE = {"TP": "green", "TN": "green", "FP": "red", "FN": "red"}


def outcome_label(value):
    return f"[{OUTCOME_STYLE[value]}]{value}[/{OUTCOME_STYLE[value]}]" if console else value


# ----------------------------------------------------------------- parte 2
def show_part2(cases, found, timing):
    variants = lambda case: ", ".join(v for v in ("patch_ok", "patch_bad") if (BENCHMARK / case["id"] / v).is_dir()) or "—"
    vulnerable = [c for c in cases if c["vulnerable"]]
    title("Benchmark de evaluación del módulo de seguridad",
          f"{len(cases)} casos etiquetados · {len(vulnerable)} vulnerables · {len(cases) - len(vulnerable)} seguros · "
          "estilo SARD / OWASP Benchmark, construido por el equipo")
    table("Casos y verdad de base", ["Caso", "Lenguaje", "Archivo", "Verdad", "Categoría", "CWE", "OWASP 2021",
                                     "Cubierto por reglas", "Parches"],
          [(c["id"], c["language"], c["file"], "Vulnerable" if c["vulnerable"] else "Seguro", c["category"],
            c.get("cwe", "—"), c.get("owasp", "—"),
            ("Sí" if c.get("in_scanner_scope") else "No") if c["vulnerable"] else "—", variants(c)) for c in cases])

    categories = {}
    for c in vulnerable:
        entry = categories.setdefault(c["category"], {"cwe": c["cwe"], "cases": 0, "scope": 0})
        entry["cases"] += 1
        entry["scope"] += bool(c["in_scanner_scope"])
    languages = sorted({c["language"] for c in cases})
    table("Composición por categoría", ["Categoría", "CWE", "Casos vulnerables", "Cubiertos por reglas"],
          [(name, e["cwe"], e["cases"], e["scope"]) for name, e in categories.items()]
          + [("Seguro (negativos)", "—", len(cases) - len(vulnerable), "—")])
    table("Composición por lenguaje", ["Lenguaje", "Casos"],
          [(language, sum(c["language"] == language for c in cases)) for language in languages])

    title("Corrida del pipeline de seguridad sobre el benchmark",
          "SAST + Secretos + SCA sobre una copia aislada de cada caso · sin modelos (0 tokens)")
    rows = []
    for c in cases:
        findings = found[c["id"]]
        result = outcome(c, findings)
        if findings:
            for f in findings:
                rows.append((c["id"], "Vulnerable" if c["vulnerable"] else "Seguro", f"{f.file_path}:{f.line_number}",
                             f.rule_id, f.severity, f.snippet, outcome_label(result)))
        else:
            rows.append((c["id"], "Vulnerable" if c["vulnerable"] else "Seguro", c["id"] + "/" + c["file"],
                         "—", "—", "(sin hallazgos)", outcome_label(result)))
    table("Hallazgos generados por caso", ["Caso", "Verdad", "Ubicación", "Regla", "Severidad", "Fragmento", "Resultado"],
          rows)

    total = sum(len(v) for v in found.values())
    seconds = sum(t["seconds"] for t in timing.values())
    table("Ejecución por escáner", ["Escáner", "Hallazgos", "Tiempo"],
          [(name, t["findings"], f"{t['seconds'] * 1000:.1f} ms") for name, t in timing.items()]
          + [("Total", total, f"{seconds * 1000:.1f} ms")])
    counts = {key: sum(outcome(c, found[c["id"]]) == key for c in cases) for key in ("TP", "FP", "FN", "TN")}
    table("Resultado de la corrida a nivel de caso", ["TP", "FP", "FN", "TN"], [tuple(counts.values())])
    if console:
        console.print("[dim]TP = vulnerable detectado · FP = seguro marcado · FN = vulnerable no detectado · "
                      "TN = seguro sin hallazgos[/dim]")


# ----------------------------------------------------------------- parte 1
SCENARIOS = [
    ("vulnerable", PERSISTS, "Escenario A · Sin cambios: el código vulnerable sigue igual"),
    ("patch_ok", RESOLVED, "Escenario B · Parche correcto aplicado"),
    ("patch_bad", PERSISTS, "Escenario C · Parche incorrecto aplicado (el defecto sigue)"),
]


def run_reviewer(root: Path, cases: list[dict], found: dict):
    """Re-ejecuta el reviewer sobre cada hallazgo tras aplicar cada variante del código."""
    reviewer = SecurityVerifierAgent(target_repo_path=str(root))
    results = []
    for variant, expected, label in SCENARIOS:
        started = time.perf_counter()
        rows = []
        for case in cases:
            findings = found.get(case["id"]) or []
            if not findings or not (BENCHMARK / case["id"] / variant).is_dir():
                continue
            place(root, case, variant)
            for review in reviewer.review_all_findings(findings)["findings_status"]:
                rows.append({"case": case["id"], "review": review, "expected": expected,
                             "correct": review["status"] == expected})
        results.append({"variant": variant, "label": label, "expected": expected, "rows": rows,
                        "seconds": time.perf_counter() - started})
        for case in cases:  # restaurar el código original antes del siguiente escenario
            if (BENCHMARK / case["id"] / "vulnerable").is_dir():
                place(root, case, "vulnerable")
    return results


def show_part1(results, found):
    total = sum(len(v) for v in found.values())
    title("SecurityVerifierAgent · Reviewer de hallazgos de seguridad",
          f"Re-ejecuta el escáner en sandbox y decide si cada hallazgo PERSISTE o fue RESUELTO · "
          f"{total} hallazgos de partida · 0 llamadas a modelos (0 tokens)")
    for scenario in results:
        rows = []
        for row in scenario["rows"]:
            review = row["review"]
            rows.append((row["case"], f"{review['file_path']}:{review['line_number']}", review["rule_id"],
                         status_label(row["expected"]), status_label(review["status"]), check(row["correct"]),
                         review["justification"]))
        table(scenario["label"], ["Caso", "Ubicación", "Regla", "Esperado", "Reviewer", "", "Justificación"], rows)

    title("Resumen del Reviewer por escenario")
    rows = []
    for scenario in results:
        statuses = [row["review"]["status"] for row in scenario["rows"]]
        hits = sum(row["correct"] for row in scenario["rows"])
        rows.append((scenario["label"].split(":")[0], len(statuses), statuses.count(PERSISTS), statuses.count(RESOLVED),
                     statuses.count(NOT_VERIFIED), f"{hits}/{len(statuses)}", f"{scenario['seconds'] * 1000:.1f} ms"))
    table("", ["Escenario", "Revisados", "PERSISTS", "RESOLVED", "NOT_VERIFIED", "Aciertos", "Tiempo"], rows)
    errors = [row for scenario in results for row in scenario["rows"] if not row["correct"]]
    if errors:
        title("Desacuerdos del Reviewer con la verdad de base",
              "Casos donde la decisión no coincide con lo esperado; se reportan sin ocultar.")
        table("", ["Escenario", "Caso", "Esperado", "Reviewer", "Justificación"],
              [(s["label"].split(":")[0], r["case"], status_label(r["expected"]), status_label(r["review"]["status"]),
                r["review"]["justification"]) for s in results for r in s["rows"] if not r["correct"]])


# ----------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="Corrida y métricas del módulo de seguridad")
    parser.add_argument("--parte", choices=["1", "2"], default="1",
                        help="1 = Reviewer de hallazgos · 2 = Benchmark y corrida del pipeline")
    args = parser.parse_args()

    cases = load_cases()
    with tempfile.TemporaryDirectory(prefix="veraud-security-benchmark-") as workspace:
        root = Path(workspace)
        for case in cases:
            place(root, case, "vulnerable" if case["vulnerable"] else "safe")
        found, timing = scan(root, cases)
        if args.parte == "1":
            show_part1(run_reviewer(root, cases, found), found)
        elif args.parte == "2":
            show_part2(cases, found, timing)


if __name__ == "__main__":
    main()

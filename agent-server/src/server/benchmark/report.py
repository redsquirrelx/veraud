import json
from collections import Counter
from pathlib import Path
from statistics import mean, median

from .metrics import human_scores, judge_scores, review_template, stability
from .schemas import BenchmarkSuite, HumanReview


def average(values):
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def stage_summary(records, name):
    stages = [record["stages"][name] for record in records]
    times = sorted(stage["seconds"] for stage in stages if "seconds" in stage)
    telemetry = [stage["telemetry"] for stage in stages if "telemetry" in stage]
    costs = [item["cost_usd"] for item in telemetry]
    return {
        "statuses": dict(Counter(stage["status"] for stage in stages)),
        "seconds_mean": average(times), "seconds_median": median(times) if times else None,
        "calls": sum(item["calls"] for item in telemetry),
        "failed_calls": sum(item["failed_calls"] for item in telemetry),
        "retry_attempts": sum(item.get("retry_attempts", 0) for item in telemetry),
        "rate_limit_events": sum(item.get("rate_limit_events", 0) for item in telemetry),
        "wait_seconds": sum(item.get("wait_seconds", 0.0) for item in telemetry),
        "invalid_json_calls": sum(item["invalid_json_calls"] for item in telemetry),
        "usage_calls": sum(item["usage_calls"] for item in telemetry),
        "observed_input_tokens": sum(item["observed_input_tokens"] or 0 for item in telemetry) if any(item["usage_calls"] for item in telemetry) else None,
        "observed_output_tokens": sum(item["observed_output_tokens"] or 0 for item in telemetry) if any(item["usage_calls"] for item in telemetry) else None,
        "cost_usd": sum(costs) if costs and all(cost is not None for cost in costs) else None,
    }


def build_report(output: Path):
    suite = BenchmarkSuite.model_validate(json.loads((output / "suite.json").read_text(encoding="utf-8")))
    cases = {case.id: case for case in suite.cases}
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((output / "runs").glob("*.json"))]
    humans = []
    rows = []
    for record in records:
        review_path = output / "reviews" / f"{record['run_id']}.json"
        review = HumanReview.model_validate(json.loads(review_path.read_text(encoding="utf-8")))
        human = human_scores(review, review_template(record, cases[record["case_id"]]))
        humans.append(human)
        rows.append({
            "run_id": record["run_id"], "case_id": record["case_id"],
            "pipeline_status": record["pipeline_status"], "total_seconds": record["total_seconds"],
            "stages": {name: stage["status"] for name, stage in record["stages"].items()},
            "automatic": record["automatic"], "human": human,
            "judge_calibration": record["judge_calibration"],
        })
    calibration = [item for record in records for item in record["calibration_items"]]
    reviewed = [item for item in humans if item["claims_reviewed"]]
    summary = {
        "runs": len(records), "pipeline_statuses": dict(Counter(record["pipeline_status"] for record in records)),
        "kind_accuracy": average([record["automatic"]["kind_correct"] for record in records]),
        "kind_scored_runs": sum(record["automatic"]["kind_correct"] is not None for record in records),
        "language_accuracy": average([record["automatic"]["language_correct"] for record in records]),
        "entrypoint_reference_recall": average([record["automatic"]["entrypoints"]["reference_recall"] for record in records]),
        "component_reference_recall": average([record["automatic"]["key_components"]["reference_recall"] for record in records]),
        "citation_validity": average([record["automatic"]["citation_validity"] for record in records]),
        "human_reviewed_runs": len(reviewed),
        "human_support_rate": average([item["support_rate"] for item in reviewed]),
        "human_expected_fact_recall": average([item["expected_fact_recall"] for item in humans]),
        "judge_calibration": judge_scores(calibration),
        "calibration_expected_items": sum(record["calibration_expected_items"] for record in records),
        "stages": {name: stage_summary(records, name) for name in ("analyzer", "architect", "judge", "judge_calibration")},
        "stability": {case_id: stability([record for record in records if record["case_id"] == case_id]) for case_id in sorted({record["case_id"] for record in records})},
    }
    environment = json.loads((output / "environment.json").read_text(encoding="utf-8"))
    summary["planned_runs"] = environment.get("sampling", {}).get("planned_runs")
    return {"summary": summary, "runs": rows}


def display(value, percent=False):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if percent:
        return f"{100 * value:.1f}%"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def markdown(report):
    summary = report["summary"]
    judge = summary["judge_calibration"]
    lines = [
        "# Workspace agent benchmark", "",
        f"Runs: **{summary['runs']}** / {display(summary['planned_runs'])} planned. Pipeline statuses: `{summary['pipeline_statuses']}`.", "",
        "## Quality", "", "| Metric | Value |", "|---|---:|",
        f"| Analyzer kind accuracy ({summary['kind_scored_runs']} eligible runs) | {display(summary['kind_accuracy'], True)} |",
        f"| Primary language accuracy | {display(summary['language_accuracy'], True)} |",
        f"| Entrypoint reference recall | {display(summary['entrypoint_reference_recall'], True)} |",
        f"| Key component reference recall (partial reference) | {display(summary['component_reference_recall'], True)} |",
        f"| Citation validity (existence/ranges, not semantic support) | {display(summary['citation_validity'], True)} |",
        f"| Judge labeled-claim accuracy | {display(judge['accuracy'], True)} |",
        f"| Judge macro-F1 | {display(judge['macro_f1'])} |",
        f"| Judge false support rate (contradicted → supported) | {display(judge['false_support_rate'], True)} |",
        f"| Human support rate ({summary['human_reviewed_runs']} reviewed runs) | {display(summary['human_support_rate'], True)} |",
        f"| Human expected-fact recall | {display(summary['human_expected_fact_recall'], True)} |", "",
        f"Judge calibration coverage: {judge['items']}/{summary['calibration_expected_items']} labeled claims. Missing judgments are not scored as correct.", "",
        "## Time, calls and observed usage", "",
        "| Stage | Mean seconds | Median seconds | Calls | Failed | Retries | HTTP 429 | Wait seconds | Invalid JSON | Usage calls | Input tokens | Output tokens | USD | Statuses |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, stage in summary["stages"].items():
        lines.append(f"| {name} | {display(stage['seconds_mean'])} | {display(stage['seconds_median'])} | {stage['calls']} | {stage['failed_calls']} | {stage['retry_attempts']} | {stage['rate_limit_events']} | {display(stage['wait_seconds'])} | {stage['invalid_json_calls']} | {stage['usage_calls']}/{stage['calls']} | {display(stage['observed_input_tokens'])} | {display(stage['observed_output_tokens'])} | {display(stage['cost_usd'])} | `{stage['statuses']}` |")
    lines += ["", "Calibration is additional evaluation work, separate from production judge cost. Missing usage/prices are unknown, never zero. With few repeats, timing and stability are descriptive, not statistical guarantees.", "", "## Per run", "", "| Run | Analyzer | Architect | Judge | Kind correct | Entrypoint recall | Component recall | Total seconds |", "|---|---|---|---|---|---:|---:|---:|"]
    for row in report["runs"]:
        scores = row["automatic"]
        lines.append(f"| {row['run_id']} | {row['stages']['analyzer']} | {row['stages']['architect']} | {row['stages']['judge']} | {display(scores['kind_correct'])} | {display(scores['entrypoints']['reference_recall'], True)} | {display(scores['key_components']['reference_recall'], True)} | {display(row['total_seconds'])} |")
    lines += ["", "## Stability (completed, non-degraded upstream runs only)", "", "| Case | Eligible runs | Pairs | Kind agreement | Style agreement | Component Jaccard | Quality-evidence Jaccard |", "|---|---:|---:|---:|---:|---:|---:|"]
    for case_id, values in summary["stability"].items():
        lines.append(f"| {case_id} | {values['eligible_runs']} | {values['pairs']} | {display(values['kind_agreement'], True)} | {display(values['style_agreement'], True)} | {display(values['component_jaccard'])} | {display(values['quality_evidence_jaccard'])} |")
    lines += ["", "Exact-text/evidence agreement is not semantic equivalence. Review templates cover summary, style, intention, flow, responsibilities, notes, deviations, containers and risks. Fill their verdict/found fields and rerun `benchmark report`.", ""]
    lines += ["Stage durations include pacing/backoff waits. Retry counts describe benchmark adapter attempts; SDK-internal retries are not individually observed. A recovered retry does not mark a call as failed. Unknown usage for failed attempts leaves cost unscored.", ""]
    return "\n".join(lines)


def write_report(output: Path):
    report = build_report(output)
    (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    return report

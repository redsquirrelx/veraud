"""Development harness: score a TestControllabilityAgent result against an evaluator-only fixture.

The *-defects.json files are measurement oracles, never agent inputs. They
are not exposed to the agent and are not imported by any runtime code; this
script only compares outputs after a run.

Fixture schema (civitaspermit-01, solsticegrid-01):
- defects[]: expected findings. code_evidence.path is the inspected source
  path; code_evidence.excerpt carries a source fragment; category is a free
  text class label.
- negative_controls[]: source.path entries that must NOT be attributed to a
  finding.

Matching (documented, deterministic):
- Component match: the expected code_evidence.path appears in a candidate or
  finding's components, or the expected component class name appears in the
  record text (title/description/justification/modularity_impact/recommendation/
  observed_mechanisms/substitution_blockers), case-insensitively.
- Mechanism match: any identifier token (len >= 4) from the expected
  code_evidence.excerpt, or any meaningful token of the expected category
  (len >= 4, stopwords removed, split on separators), appears in the same
  record text, case-insensitively.
- A case counts as detected when both match in the same record; candidates
  produced by the investigator count alongside final findings.
- A negative control counts as respected when no candidate/finding points at
  the control's path (components or resolved evidence); text mentions do not
  count as attribution.

Usage: uv run python src/test-agents/evaluate_test_controllability.py --result out.json --defects examples/testcontrollability/civitaspermit-01/civitaspermit-01-defects.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

_CATEGORY_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "onto", "sobre",
    "para", "con", "una", "unos", "como", "porque", "where", "when",
})


def _tokens(text):
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_.]+", text or "")
        if len(token) >= 4}


def _identifier_tokens(excerpt):
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", excerpt or "")
    tokens = {token.lower() for token in raw if len(token) >= 4}
    dotted = re.findall(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", excerpt or "")
    return tokens | {token.lower() for token in dotted}


def _record_text(record):
    parts = []
    for field in ("title", "description", "justification", "modularity_impact", "recommendation"):
        parts.append(record.get(field, ""))
    parts.extend(record.get("observed_mechanisms") or [])
    parts.extend(record.get("substitution_blockers") or [])
    return " ".join(parts)


def _records(result):
    """Candidate and finding records that may carry a defect."""
    records = []
    records.extend(result.get("candidates") or [])
    records.extend(result.get("findings") or [])
    return records


def _component_match(record, case):
    path = (case.get("code_evidence") or {}).get("path", "")
    if path and path in (record.get("components") or []):
        return True
    component = case.get("component", "")
    return bool(component and component.lower() in _record_text(record).lower())


def _control_match(record, control):
    """A control is violated only if the record points at the control itself."""
    path = (control.get("source") or {}).get("path", "")
    if not path:
        return False
    if path in (record.get("components") or []):
        return True
    evidence_paths = [item.get("path", "") for item in record.get("evidence") or []]
    return path in evidence_paths


def _mechanism_match(record, case):
    text = _record_text(record).lower()
    excerpt_tokens = _identifier_tokens((case.get("code_evidence") or {}).get("excerpt", ""))
    if any(token in text for token in excerpt_tokens):
        return True
    category_tokens = {token for token in re.split(r"[-_/\\(), ]+", (case.get("category") or "").lower())
        if len(token) >= 4 and token not in _CATEGORY_STOPWORDS}
    return any(token in text for token in category_tokens)


def evaluate(result, defects):
    records = _records(result)
    lines = []
    detected = []
    for case in defects.get("defects", []):
        matches = list(dict.fromkeys(
            record.get("id") for record in records
            if _component_match(record, case) and _mechanism_match(record, case)))
        lines.append(f"{case['id']}: {'DETECTED by ' + ', '.join(matches) if matches else 'MISSED'}")
        if matches:
            detected.append(case["id"])
    false_positives = []
    for control in defects.get("negative_controls", []):
        hits = [record.get("id") for record in records if _control_match(record, control)]
        lines.append(f"{control['id']}: {'RESPECTED' if not hits else 'FALSE POSITIVE by ' + ', '.join(hits)}")
        if hits:
            false_positives.append(control["id"])
    total = len(defects.get("defects", []))
    summary = {
        "project": defects.get("project"),
        "expected_defects": total,
        "detected": len(detected),
        "missed": [case["id"] for case in defects.get("defects", []) if case["id"] not in detected],
        "negative_controls": len(defects.get("negative_controls", [])),
        "false_positives": false_positives,
        "total_records": len(records),
        "record_ids": [record.get("id") for record in records],
    }
    return lines, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--defects", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="Print only the JSON summary.")
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    defects = json.loads(args.defects.read_text(encoding="utf-8"))
    lines, summary = evaluate(result, defects)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not summary["missed"] and not summary["false_positives"] else 1
    print(f"project: {summary['project']}  ({summary['detected']}/{summary['expected_defects']} detected, "
          f"{len(summary['false_positives'])} false positives, {summary['total_records']} records)")
    for line in lines:
        print(f"  {line}")
    if summary["missed"]:
        print(f"missed: {', '.join(summary['missed'])}")
    if summary["false_positives"]:
        print(f"false positives: {', '.join(summary['false_positives'])}")
    return 0 if not summary["missed"] and not summary["false_positives"] else 1


if __name__ == "__main__":
    sys.exit(main())

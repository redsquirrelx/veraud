"""Development harness: score an agent result against an evaluator-only fixture.

The *-defects.json files are measurement oracles, never agent inputs. They
are not exposed to the agent and are not imported by any runtime code; this
script only compares outputs after a run.

Matching (documented, deterministic):
- Component match: the expected code_evidence.path appears in a finding's
  components, or the expected component class name appears in the finding
  text (title/description/justification/modularity_impact/recommendation),
  case-insensitively.
- Mechanism match: any identifier token (len >= 4) from the expected
  code_evidence.exact_excerpt, or any meaningful token of the expected
  category, appears in the finding text (case-insensitive).
- A case counts as detected when both match in the same finding.
- A negative control counts as respected when no finding component-matches
  the control's path/class; a finding there is reported as a false positive.

Usage: uv run python src/test-agents/evaluate_test_isolation.py --result out.json --defects examples/harborcold-01/harborcold-01-defects.json
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
    # Dotted/compound tokens keep their raw form for direct substring matching.
    dotted = re.findall(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", excerpt or "")
    return tokens | {token.lower() for token in dotted}


def _finding_text(finding):
    parts = [finding.get(field, "") for field in (
        "title", "description", "justification", "modularity_impact", "recommendation")]
    return " ".join(parts)


def _component_match(finding, case):
    path = (case.get("code_evidence") or {}).get("path", "")
    if path and path in (finding.get("components") or []):
        return True
    component = case.get("component", "")
    return bool(component and component.lower() in _finding_text(finding).lower())


def _control_match(finding, control):
    """A control is violated only if the finding points at the control itself.

    Components and evidence paths are exact, host-verified paths, so this is
    airtight: a finding about an unrelated file whose prose mentions the word
    is not attribution.
    """
    path = control.get("path", "")
    if not path:
        return False
    if path in (finding.get("components") or []):
        return True
    evidence_paths = [item.get("path", "") for item in finding.get("evidence") or []]
    return path in evidence_paths


def _mechanism_match(finding, case):
    text = _finding_text(finding).lower()
    excerpt_tokens = _identifier_tokens((case.get("code_evidence") or {}).get("exact_excerpt", ""))
    if any(token in text for token in excerpt_tokens):
        return True
    category_tokens = {token for token in re.split(r"[-_]", case.get("category", "").lower())
        if len(token) >= 4 and token not in _CATEGORY_STOPWORDS}
    return any(token in text for token in category_tokens)


def evaluate(result, defects):
    findings = result.get("findings") or []
    lines = []
    detected = []
    for case in defects.get("confirmed_cases", []):
        matches = [finding.get("id") for finding in findings
            if _component_match(finding, case) and _mechanism_match(finding, case)]
        lines.append(f"{case['id']}: {'DETECTED by ' + ', '.join(matches) if matches else 'MISSED'}")
        if matches:
            detected.append(case["id"])
    false_positives = []
    for control in defects.get("negative_controls", []):
        hits = [finding.get("id") for finding in findings if _control_match(finding, control)]
        lines.append(f"{control['id']}: {'RESPECTED' if not hits else 'FALSE POSITIVE by ' + ', '.join(hits)}")
        if hits:
            false_positives.append(control["id"])
    total = len(defects.get("confirmed_cases", []))
    summary = {
        "fixture": defects.get("fixture"),
        "expected_findings": total,
        "detected": len(detected),
        "missed": [case["id"] for case in defects.get("confirmed_cases", []) if case["id"] not in detected],
        "negative_controls": len(defects.get("negative_controls", [])),
        "false_positives": false_positives,
        "total_findings": len(findings),
        "findings_ids": [finding.get("id") for finding in findings],
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
    print(f"fixture: {summary['fixture']}  ({summary['detected']}/{summary['expected_findings']} detected, "
          f"{len(summary['false_positives'])} false positives, {summary['total_findings']} findings)")
    for line in lines:
        print(f"  {line}")
    if summary["missed"]:
        print(f"missed: {', '.join(summary['missed'])}")
    if summary["false_positives"]:
        print(f"false positives: {', '.join(summary['false_positives'])}")
    return 0 if not summary["missed"] and not summary["false_positives"] else 1


if __name__ == "__main__":
    sys.exit(main())

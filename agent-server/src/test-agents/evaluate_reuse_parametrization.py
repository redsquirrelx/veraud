"""Evaluate reuse-parametrization investigation output against an evaluator-only defect oracle.

The oracle (cycleharbor-extended-defects.json) is NOT given to any model;
it is only matched deterministically against the investigator's lifted findings.

    uv run python src/test-agents/evaluate_reuse_parametrization.py \
        --output examples/cycleharbor-extended/run2_output.json \
        --defects examples/cycleharbor-extended/cycleharbor-extended-defects.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Each signature: file path suffix + identifiers that must appear in the finding text.
SIGNATURES = {
    "CH-P01": ("integrations/payments.py", ["PaymentReceipt", "ProcessorPaymentAdapter", "dict", "dictionary"]),
    "CH-P02": ("payments/settlement.py", ["ProcessorPaymentAdapter", "SettlementService", "result[", "paid", "dict"]),
    "CH-F01": ("pricing/policies.py", ["PromotionalFarePolicy", "negative", "amount_cents", "FareQuote"]),
    "CH-Q01": ("maintenance/triage.py", ["MemoryRepairQueue", "tickets", "enqueue"]),
    "CH-F02": ("pricing/alternatives.py", ["WeekendFarePolicy", "dict", "dictionary"]),
    "CH-F03": ("pricing/alternatives.py", ["CappedFarePolicy", "aggregate", "ride_id"]),
    "CH-F04": ("pricing/selection.py", ["FareSelectionService", "FlatFarePolicy", "MinuteFarePolicy"]),
    "CH-P03": ("integrations/payment_alternatives.py", ["TerminalGateway", "None", "PaymentReceipt", "capture"]),
    "CH-K01": ("integrations/legacy_locks.py", ["LegacyDockLockAdapter", "send_command", "DockController", "bool"]),
    "CH-K02": ("rides/kiosk.py", ["KioskUnlockService", "SimulatedLockGateway", "LockGateway"]),
    "CH-C01": ("storage/alternatives.py", ["JsonBicycleCatalog", "available_at", "find"]),
    "CH-C02": ("storage/alternatives.py", ["SqlRideRepository", "find", "dict"]),
    "CH-C03": ("fleet/inspection.py", ["FleetInspection", "_bikes", "MemoryBicycleCatalog", "_rides", "inspection"]),
    "CH-C04": ("reporting/exports.py", ["RideExport", "_rides", "MemoryRideRepository", "export"]),
    "CH-N01": ("notifications/provider_alternatives.py", ["EmailMessageAdapter", "submit", "dict", "provider"]),
    "CH-N02": ("notifications/receipt_delivery.py", ["ReceiptDeliveryService", "transport", "SmsMessageAdapter"]),
    "CH-N03": ("notifications/campaigns.py", ["RiderCampaignService", "messages", "template"]),
    "CH-Q02": ("maintenance/dispatch.py", ["MaintenanceDispatchService", "tickets", "enqueue"]),
}

NEGATIVE_CONTROL_PATHS = [
    "src/cycleharbor/integrations/locks.py",
    "src/cycleharbor/pricing/alternatives.py",
    "src/cycleharbor/integrations/payment_alternatives.py",
    "src/cycleharbor/storage/alternatives.py",
    "src/cycleharbor/notifications/provider_alternatives.py",
    "src/cycleharbor/maintenance/alternatives.py",
    "src/cycleharbor/fleet/reservations.py",
    "src/cycleharbor/rides/activation.py",
    "src/cycleharbor/bootstrap.py",
]

TEXT_FIELDS = ("title", "description", "justification", "modularity_impact", "recommendation", "summary", "rationale")


def finding_text(finding):
    parts = [str(finding.get(field, "")) for field in TEXT_FIELDS]
    return " ".join(parts).lower()


def finding_paths(finding):
    paths = []
    for key in ("components",):
        paths.extend(finding.get(key, []))
    for key in ("evidence",):
        for reference in finding.get(key, []):
            path = reference.get("path") if isinstance(reference, dict) else None
            if path:
                paths.append(path)
    for key in ("implementations", "consumers"):
        paths.extend(finding.get(key, []))
    return [path.replace("\\", "/") for path in paths if isinstance(path, str)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--defects", type=Path, required=True)
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()

    result = json.loads(args.output.read_text(encoding="utf-8"))
    defects = json.loads(args.defects.read_text(encoding="utf-8"))
    confirmed = {case["id"]: case for case in defects["confirmed_cases"]}
    findings = list(result.get("findings") or [])
    for item in result.get("investigation_results") or []:
        # Investigation-local candidates are not lifted findings but count as detections.
        for candidate in item.get("candidates") or []:
            if candidate.get("id") and not any(finding.get("id") == candidate["id"] for finding in findings):
                if candidate.get("kind") == "violation" or candidate.get("severity") in {"high", "critical"}:
                    finding = dict(candidate)
                    finding["_origin"] = item.get("investigation_id")
                    findings.append(finding)

    hits = {}
    for case_id, (suffix, keywords) in SIGNATURES.items():
        witness = []
        for finding in findings:
            paths = finding_paths(finding)
            if not any(path.lower().endswith(suffix.lower()) for path in paths):
                continue
            text = finding_text(finding)
            if any(keyword.lower() in text for keyword in keywords):
                witness.append(finding.get("id") or finding.get("title", "?")[:60])
        if witness:
            hits[case_id] = witness

    suspicious = []
    for finding in findings:
        paths = finding_paths(finding)
        for control in NEGATIVE_CONTROL_PATHS:
            if any(path.lower().endswith(control.lower().replace("src/", "", 1)) or path.lower().endswith(control.lower())
                   for path in paths):
                suspicious.append({"control_path": control, "finding": finding.get("id") or finding.get("title", "?")[:60]})

    print(f"Investigation findings lifted: {len(result.get('findings') or [])}")
    print(f"Finding candidates considered: {len(findings)}")
    print(f"Confirmed cases covered: {len(hits)}/{len(confirmed)}")
    uncovered = [case_id for case_id in confirmed if case_id not in hits]
    if uncovered:
        print(f"Uncovered: {', '.join(sorted(uncovered))}")
    print()
    print("Per-case coverage:")
    for case_id in sorted(confirmed):
        status = "HIT " if case_id in hits else "miss"
        witnesses = ", ".join(hits[case_id][:2]) if case_id in hits else "-"
        print(f"  [{status}] {case_id}  {witnesses}")
    print()
    print(f"Findings citing negative-control sites (not adjudicated, informational): {len(suspicious)}")
    for item in suspicious[:20]:
        print(f"    - {item['finding']} -> {item['control_path']}")
    if args.json_report:
        args.json_report.write_text(json.dumps({
            "findings_lifted": len(result.get("findings") or []),
            "findings_considered": len(findings),
            "covered": sorted(hits),
            "uncovered": sorted(uncovered),
            "suspicious_on_controls": suspicious,
        }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

"""Validate retained receipts using the existing snapshot, without retrieving bytes."""

from collections import defaultdict

from pydantic import TypeAdapter

from server.contracts.audit import EvidenceReference
from server.runtimes.coordination.synthesis import stable_id
from server.runtimes.investigation.structured import safe_diagnostic

from .delegation import assignment_identifier, coordinator_request, validate_output
from .registry import registered_coordinators
from .schemas import AuditFinding, AuditIssue, CollectedAssessment, FindingOrigin
from .validation import validate_plan


def objects(value, location="", scope="", *, include_inputs=True):
    if isinstance(value, dict):
        scope = value.get("invocation_id") or value.get("assignment", {}).get("invocation_id") or scope
        yield value, location, scope
        for key, item in value.items():
            if include_inputs or key not in {"request", "initial_plan", "execution_records", "continuations", "continuation", "documented_architecture"}:
                yield from objects(item, f"{location}/{key}", scope, include_inputs=include_inputs)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from objects(item, f"{location}/{index}", scope, include_inputs=include_inputs)


def collect_assessments(execution, state):
    specs, assessments, issues = registered_coordinators(), [], []
    plan, request = state.get("plan"), state["request"]
    available = {capability.id for capability in state["coordinator_catalog"]}
    if plan is None:
        issues.append(AuditIssue(code=state.get("termination_reason") or "missing_plan", message="No valid audit plan was produced."))
    expected = {assignment_identifier(state["snapshot_hash"], i, a): a for i, a in enumerate(plan.assignments if plan else [])}
    receipts = defaultdict(list)
    for record in state.get("coordinator_results", []):
        receipts[record.assignment_id].append(record)
    snapshot = execution.tools.accessible_snapshot
    identity = {"repository_id": snapshot.repository.name, "commit": snapshot.repository.commit, "snapshot_hash": snapshot.repository.snapshot_hash}
    paths, files = {f.path for f in snapshot.files}, {f.id: f for f in snapshot.files}
    for identifier in dict.fromkeys([*expected, *receipts]):
        rows, assignment = receipts[identifier], expected.get(identifier)
        row = rows[0] if rows else None
        coordinator = assignment.coordinator_id if assignment else row.assignment.coordinator_id
        spec = specs.get(coordinator)
        local = []

        def issue(code, message, location="", local=local, identifier=identifier):
            local.append(AuditIssue(code=code, assignment_id=identifier, location=location, message=message))

        collected = CollectedAssessment(assignment_id=identifier, coordinator_id=coordinator,
            status=row.status if row else "skipped", result_kind=spec.result_kind if spec else "planning")
        if len(rows) > 1:
            issue("duplicate_receipt", "Repeated assignment receipt retained in raw results; evaluated only once.")
        ambiguous = len({r.model_dump_json() for r in rows}) > 1
        try:
            if row is None:
                issue("missing_receipt", "Selected assignment has no execution receipt.")
            elif assignment is None or assignment != row.assignment or spec is None or coordinator not in available or ambiguous:
                raise ValueError("unassigned_or_ambiguous_receipt")
            elif row.result is not None:
                if any(state[key] != value for key, value in identity.items()):
                    raise ValueError("manager_repository_mismatch")
                validated = validate_plan(plan.model_copy(update={"assignments": [assignment]}), request,
                    {coordinator: spec.capability}, paths).assignments[0]
                sent = coordinator_request(spec, request, validated).model_dump(mode="json")
                if row.request != sent or not isinstance(row.result, dict):
                    raise ValueError("invalid_request_or_result")
                validate_output(row.result, sent, identity)
                if spec.result_class is not None:
                    TypeAdapter(spec.result_class).validate_python(row.result)
                raw = row.result
                if any(type(value) is not int or value < 0 for value in raw.get("consumption", {}).values() if not isinstance(value, bool)):
                    issue("invalid_consumption", "Raw consumption contains invalid quantities; charged receipt metrics are preserved.")
                collected = collected.model_copy(update={"reported_coverage": raw.get("coverage"),
                    "inconclusive": [*raw.get("material_gaps", []), *raw.get("missing_information", []),
                        *raw.get("inconclusive_investigations", []), *raw.get("uncovered_requirements", [])]})
                if row.failure or row.status in {"failed", "timeout", "skipped"}:
                    collected = collected.model_copy(update={"status": row.status if row.status in {"failed", "timeout", "skipped"} else "failed"})
                elif spec.result_kind == "planning":
                    collected = collected.model_copy(update={"status": "partial",
                        "inconclusive": [*collected.inconclusive, *raw.get("plan", {}).get("uncovered_requirements", []),
                            "Coordinator produced planning only, not a technical assessment."]})
                    if raw.get("findings") or raw.get("consolidated_findings"):
                        issue("planning_findings_ignored", "Unexpected findings in a planning-only output remain in the raw receipt, not in audit findings.")
                else:
                    if raw.get("status") not in {"completed", "partial", "not_applicable"}:
                        raise ValueError("invalid_assessment_status")
                    evaluated = raw.get("coverage", {}).get("evaluated_investigation_ids", [identifier]) if isinstance(raw.get("coverage", {}), dict) else [identifier]
                    collected = collected.model_copy(update={"evaluation_performed": bool(evaluated) and raw["status"] != "not_applicable"})
                    if raw["status"] == "not_applicable":
                        collected = collected.model_copy(update={"status": "partial", "inconclusive": [*collected.inconclusive,
                            "Coordinator found no applicable investigators; no technical evaluation was performed."]})
                    evidence, by_id, by_content, scoped = {}, defaultdict(set), defaultdict(set), {}
                    for value, location, scope in objects({"result": raw, "ledger": [e.model_dump(mode="json") for e in row.evidence]}, include_inputs=False):
                        if identity.keys() <= value.keys() and any(value[key] != identity[key] for key in identity):
                            issue("nested_repository_mismatch", "Nested output does not match the audit revision.", location)
                        if not {"id", "path", "file_id", "content_hash", "snapshot_hash", "kind"} <= value.keys():
                            continue
                        try:
                            ref = EvidenceReference.model_validate(value)
                            source = files.get(ref.file_id)
                            if (not source or ref.path != source.path or ref.content_hash != source.content_hash
                                or ref.snapshot_hash != identity["snapshot_hash"] or ref.commit != identity["commit"]
                                or not ref.id or not ref.tool_call_id or ref.kind == "source" and not (
                                    ref.start_line and ref.end_line and 1 <= ref.start_line <= ref.end_line <= (source.line_count or 0))):
                                raise ValueError("invalid_evidence_identity")
                            content = ref.model_dump_json()
                            if (scope, ref.id) in scoped and scoped[scope, ref.id] != content:
                                issue("evidence_id_collision", "One evidence ID denotes different receipts within the same invocation.", location)
                            scoped[scope, ref.id] = content
                            key = stable_id("evidence", [identifier, scope, content])
                            evidence[key] = ref
                            by_id[ref.id].add(key)
                            by_id[f"{scope}/{ref.id}"].add(key)
                            by_content[content].add(key)
                        except ValueError:
                            issue("invalid_evidence", "Evidence does not match its contract or retained snapshot.", location)
                    findings, seen = [], set()
                    for field in ("findings", "consolidated_findings"):
                        values = raw.get(field, [])
                        items = values.items() if isinstance(values, dict) else enumerate(values)
                        for index, payload in items:
                            location, errors, refs = f"/{field}/{index}", [], set()
                            if not isinstance(payload, dict):
                                issue("invalid_finding", "Finding is not structured; retained in raw output.", location)
                                continue
                            local_id = payload.get("id", str(index) if isinstance(values, dict) else "")
                            if not isinstance(local_id, str) or not local_id:
                                errors.append("missing_finding_id")
                            if (field, local_id) in seen:
                                errors.append("duplicate_finding_id")
                            seen.add((field, local_id))
                            if isinstance(values, dict) and payload.get("id", str(index)) != str(index):
                                errors.append("finding_key_mismatch")
                            invocations = {item.get("assignment", {}).get("invocation_id"): item for item in raw.get("invocations", [])}
                            for contribution in payload.get("contributions", []):
                                invocation = invocations.get(contribution.get("invocation_id"), {})
                                original = contribution.get("finding", {})
                                child = invocation.get("result") or {}
                                if (not invocation or original not in child.get("findings", [])
                                    or contribution.get("investigator_id") != invocation.get("assignment", {}).get("investigator_id")
                                    or contribution.get("reference") != f"{contribution.get('invocation_id')}/{original.get('id')}"
                                    or any(child.get(key) != identity[key] for key in identity)):
                                    errors.append("unsupported_contribution")
                            for value, _, _ in objects(payload):
                                if {"id", "path", "file_id", "content_hash", "snapshot_hash", "kind"} <= value.keys():
                                    try:
                                        keys = by_content.get(EvidenceReference.model_validate(value).model_dump_json(), set())
                                    except ValueError:
                                        keys = set()
                                    refs.update(keys)
                                    if not keys:
                                        errors.append("invalid_finding_evidence")
                                for key in ("evidence_ids", "code_evidence_ids", "evidence_refs"):
                                    inline = {e.get("id"): e for e in value.get("evidence", []) if isinstance(e, dict)}
                                    for citation in value.get(key, []):
                                        if citation in inline:
                                            try:
                                                keys = by_content.get(EvidenceReference.model_validate(inline[citation]).model_dump_json(), set())
                                            except ValueError:
                                                keys = set()
                                        else:
                                            keys = by_id.get(citation, set())
                                        if not keys or len({evidence[k].model_dump_json() for k in keys}) > 1:
                                            errors.append("unresolved_evidence_id")
                                        else:
                                            refs.update(keys)
                            if not any(evidence[key].kind == "source" for key in refs):
                                errors.append("no_verified_source")
                            for code in sorted(set(errors)):
                                issue(code, "Finding retained with an integrity limitation; no new validation verdict inferred.", location)
                            if payload.get("status") in {"disputed", "inconclusive"}:
                                collected = collected.model_copy(update={"inconclusive": [*collected.inconclusive,
                                    {"location": location, "status": payload["status"]}]})
                            findings.append(AuditFinding(payload=payload, origins=[FindingOrigin(assignment_id=identifier,
                                coordinator_id=coordinator, finding_id=local_id if isinstance(local_id, str) and local_id else None, location=location)],
                                evidence_refs=sorted(refs), integrity_issues=sorted(set(errors))))
                    collected = collected.model_copy(update={"findings": findings, "evidence": evidence,
                        "status": "partial" if raw["status"] == "partial" or local or collected.inconclusive else collected.status})
            elif row.status in {"completed", "partial"}:
                raise ValueError("missing_result")
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            issue("invalid_assessment", safe_diagnostic(error))
            collected = collected.model_copy(update={"status": "failed", "findings": [], "evidence": {}})
        if row and row.failure:
            issue(row.failure.code, row.failure.summary)
        collected = collected.model_copy(update={"issues": local})
        assessments.append(collected)
        issues.extend(local)
    return {"assessments": assessments, "collection_issues": issues}

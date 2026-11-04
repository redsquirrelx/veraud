"""Validate consumed extension shapes while preserving unknown domain data."""

from server.reporting.interpretation import ANALYSIS_FIELDS


def validate_extensions(records):
    def require(value, schema, path):
        if not isinstance(value, schema):
            raise ValueError(f"Invalid Blackboard extension at {path}: expected {schema.__name__}.")  # noqa: TRY004 - Pydantic input error

    object_fields = {"report", "investigation", "audit_context", "audit_outcome", "report_facts", "coverage",
        "assignment", "consumption", "hypothesis_validation_issues"}
    object_lists = {"invocations", "assessments", "hypotheses", "findings", "consolidated_findings", "contributions",
        "relationships", "links", "finding_relationships", "commitments", "material_gaps", "unresolved_gaps", "gaps"}
    text_lists = {"limitations", "conditions", "assumptions", "unknowns", "missing_information", "finding_refs",
        "withdrawn_finding_refs", "resolved_gap_ids", "evidence_ids", "declaration_ids", "component_ids", "group_ids",
        "subject_ids", "assessment_ids", "validation_issues", "pending_evaluation_evidence_ids", "components",
        "supporting_evidence_ids", "demonstration_evidence_ids", "seam_evidence_ids"}

    def visit(value, path):
        require(value, dict, path)
        if "entity_catalog" in value:
            require(value["entity_catalog"], list, path + ".entity_catalog")
            for entity in value["entity_catalog"]:
                require(entity, dict, path + ".entity_catalog")
                require(entity.get("id"), str, path + ".entity_catalog.id")
                for key in ("name", "path", "file_id", "kind"):
                    if key in entity:
                        require(entity[key], str, path + ".entity_catalog." + key)
        for key, item in value.items():
            location = path + "." + key
            if item is None and key in {"plan", "result", "critical_review"}:
                continue
            if key == "findings" and isinstance(item, dict):
                for identifier, finding in item.items():
                    require(finding, dict, location + "/" + identifier)
                continue
            if key in object_fields or key in {"plan", "result"}:
                require(item, dict, location)
                if key not in {"coverage", "hypothesis_validation_issues", "consumption"}:
                    visit(item, location)
                if key == "hypothesis_validation_issues":
                    for values in item.values():
                        require(values, list, location)
                        for child in values:
                            require(child, str, location)
            elif key in object_lists or key in ANALYSIS_FIELDS:
                require(item, list, location)
                for index, child in enumerate(item):
                    require(child, dict, f"{location}[{index}]")
                    visit(child, f"{location}[{index}]")
                    if key == "hypotheses":
                        require(child.get("id"), str, f"{location}[{index}].id")
                    if key == "contributions" and child.get("reference") is not None:
                        require(child["reference"], str, f"{location}[{index}].reference")
                    if key in {"invocations", "assessments"}:
                        require(child.get("assignment"), dict, f"{location}[{index}].assignment")
                        require(child["assignment"].get("invocation_id"), str, f"{location}[{index}].assignment.invocation_id")
            elif key in text_lists:
                # Finding evidence inside nested investigator output is a list of
                # objects under `evidence`, not `evidence_ids`.
                require(item, list, location)
                for child in item:
                    require(child, str, location)
            elif key == "finding":
                require(item, dict, location)
                visit(item, location)
        for key in ("assessed_context", "sharing_boundary", "review_rationale", "validation_status", "category", "classification", "stable_id"):
            if key in value and value[key] is not None:
                require(value[key], str, path + "." + key)
        for key in ("id", "assessment_id", "hypothesis_id", "invocation_id", "baseline_assessment_id", "source_invocation_id", "component_id", "group_id"):
            if key in value and value[key] is not None:
                require(value[key], str, path + "." + key)
        for key in ("question", "objective", "status", "termination_reason", "rationale", "change_scenario", "snapshot_hash", "commit",
                "evaluation_evidence_status"):
            if key in value and value[key] is not None:
                require(value[key], str, path + "." + key)
        for key in ("technologies", "dependencies", "runtime_environment"):
            if key in value:
                require(value[key], list, path + "." + key)
                for item in value[key]:
                    require(item, dict, path + "." + key)
        if "coverage" in value and isinstance(value["coverage"], dict):
            for key, entries in value["coverage"].items():
                if key.startswith("unassessed_"):
                    require(entries, list, path + ".coverage." + key)
                    for entry in entries:
                        require(entry, str, path + ".coverage." + key)
        for key in ("dynamic_analysis", "strengths", "validated_architecture", "languages", "modules", "repository_structure", "targets", "exclusions"):
            if key in value:
                require(value[key], list, path + "." + key)
                for item in value[key]:
                    require(item, str, path + "." + key)

    for kind, items in records.items():
        for record in items:
            visit(record.details, f"{kind}/{record.id}/details")
            if kind == "assessments":
                for key in ("consolidated_findings", "relationships", "gaps"):
                    for index, item in enumerate(getattr(record, key)):
                        visit(item, f"{kind}/{record.id}/{key}/{index}")

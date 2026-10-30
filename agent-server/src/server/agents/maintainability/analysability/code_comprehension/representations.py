"""Bounded navigation from existing typed project results; never import their evidence ledgers."""


def project_navigation(representations, snapshot_hash):
    context, issues = {}, []
    if representations is None:
        return context, issues
    for name in ("orientation", "architecture", "semantic_validation"):
        result = getattr(representations, name)
        if result is None:
            continue
        if result.snapshot_hash != snapshot_hash:
            issues.append(f"Ignored {name} representation: snapshot mismatch.")
            continue
        if result.completion_status == "failed":
            issues.append(f"Ignored {name} representation: failed analysis.")
            continue
        if name == "orientation":
            report = result.orientation
            if report:
                context[name] = {
                    "completion_status": result.completion_status,
                    "components": [c.model_dump() for c in report.components],
                    "starting_points": [p.model_dump() for p in report.starting_points],
                    "uncertainties": list(report.uncertainties),
                }
        elif name == "architecture":
            context[name] = {
                "completion_status": result.completion_status,
                "organization": [u.model_dump() for u in result.architecture.organization],
                "connections": [c.model_dump() for c in result.architecture.connections],
                "uncertainties": list(result.architecture.uncertainties),
            }
        else:
            architecture = representations.architecture
            if architecture is not None and result.original_result != architecture:
                issues.append("Ignored semantic_validation representation: review refers to a different architecture result.")
                continue
            context[name] = {
                "completion_status": result.completion_status, "verdict": result.verdict,
                "pending_target_ids": list(result.pending_target_ids),
                "findings": [f.model_dump() for f in result.findings[:24]],
                "omitted_findings": max(0, len(result.findings) - 24),
            }
        if name in context:
            context[name]["limitations"] = list(result.limitations[:12])
    if context:
        context["notice"] = (
            "Navigation only, including supported prior claims. These evidence IDs belong to earlier stages; "
            "they are not delivered investigation citations. Inspect current snapshot source with tools. "
            "Unresolved/contradicted claims are questions, not component defects."
        )
    return context, issues

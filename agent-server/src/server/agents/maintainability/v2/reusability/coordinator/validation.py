"""Deterministic assignment integrity, never semantic selection by heuristics."""

import json

from server.runtimes.repository.access import repository_relative_path


def validate_plan(plan, request, catalog, paths):
    def accessible(target):
        return any(path == target or path.startswith(target + "/") for path in paths)

    if any(not accessible(target) for target in request.targets):
        raise ValueError("requested_scope_inaccessible")
    assignments = {}
    for assignment in plan.assignments:
        if assignment.investigator_id not in catalog:
            raise ValueError("unknown_investigator")
        try:
            targets = sorted({repository_relative_path(path) for path in assignment.targets}) or request.targets
        except ValueError:
            raise ValueError("invalid_assignment_scope") from None
        if any(not accessible(target) for target in targets):
            raise ValueError("assignment_scope_inaccessible")
        if request.targets and any(not any(target == root or target.startswith(root + "/")
            for root in request.targets) for target in targets):
            raise ValueError("assignment_scope_expansion")
        constraints = list(dict.fromkeys([*request.constraints, *catalog[assignment.investigator_id].constraints,
            *sorted(set(assignment.constraints))]))
        value = assignment.model_copy(update={"targets": targets, "constraints": constraints})
        assignments.setdefault(json.dumps(value.model_dump(), sort_keys=True), value)
    if not assignments and not any(text.strip() for text in [*plan.uncovered_requirements, *plan.limitations]):
        raise ValueError("empty_plan_without_explanation")
    return plan.model_copy(update={"assignments": [assignments[key] for key in sorted(assignments)]})

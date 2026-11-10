"""Integrity only: capability relevance remains the model's decision."""

import json

from server.runtimes.repository.access import repository_relative_path


def validate_plan(plan, request, catalog, paths):
    def accessible(target):
        return any(path == target or path.startswith(target + "/") for path in paths)

    if any(not accessible(target) for target in request.targets):
        raise ValueError("requested_scope_inaccessible")
    assignments = {}
    for assignment in plan.assignments:
        if assignment.coordinator_id not in catalog:
            raise ValueError("unknown_coordinator")
        try:
            scope = sorted({repository_relative_path(path) for path in assignment.scope}) or request.targets
        except ValueError:
            raise ValueError("invalid_assignment_scope") from None
        if any(not accessible(target) for target in scope):
            raise ValueError("assignment_scope_inaccessible")
        if request.targets and any(not any(target == root or target.startswith(root + "/")
            for root in request.targets) for target in scope):
            raise ValueError("assignment_scope_expansion")
        # Every delegated objective receives all explicit user and capability restrictions.
        constraints = list(dict.fromkeys([*request.constraints, *catalog[assignment.coordinator_id].constraints,
            *sorted(set(assignment.constraints))]))
        value = assignment.model_copy(update={"scope": scope, "constraints": constraints})
        # Canonical collection order affects identity only, never semantic similarity.
        identity = value.model_dump() | {"constraints": sorted(set(constraints))}
        key = json.dumps(identity, sort_keys=True)
        assignments.setdefault(key, value)
    if not assignments and not any(text.strip() for text in [*plan.uncovered_requirements, *plan.limitations]):
        raise ValueError("empty_plan_without_explanation")
    return plan.model_copy(update={"assignments": [assignments[key] for key in sorted(assignments)]})

"""Deterministic candidate generation, coverage policy, and follow-up admission."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import Field

from ...services.repository_analysis.context import create_identifier
from .schemas import (
    AnalysisContract,
    BudgetUsage,
    InvestigationCandidate,
    InvestigationObjective,
    InvestigationPlan,
    InvestigationProposal,
    InvestigationResult,
    PlanningDecision,
)
from .tools import RepositoryToolset

PRIORITY_ORDER = {
    "project_orientation": 0,
    "startup": 1,
    "representative_flow": 2,
    "shared_component_or_integration": 3,
    "material_uncertainty": 4,
}
EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2}


class PlanningLimits(AnalysisContract):
    max_offered_candidates: int = Field(default=100, ge=1)
    max_seed_entities: int = Field(default=12, ge=1)
    max_prompt_characters: int = Field(default=60_000, ge=8000)
    max_response_characters: int = Field(default=40_000, ge=1000)


@dataclass(frozen=True)
class CandidateCatalog:
    candidates: tuple[InvestigationCandidate, ...]
    offered_candidate_ids: tuple[str, ...]


def entity_source_paths(snapshot):
    files = {source.id: source.path for source in snapshot.files}
    paths = dict(files)
    paths.update({symbol.id: files[symbol.file_id] for symbol in snapshot.symbols})
    evidence_paths = {record.id: record.path for record in snapshot.evidence}
    for record in (*snapshot.entrypoints, *snapshot.infrastructure):
        paths[record.id] = files.get(getattr(record, "file_id", None)) or min(
            (evidence_paths[identifier] for identifier in record.evidence_ids),
            default="",
        )
    return paths


def candidate_sort_key(candidate, project_paths, entity_paths):
    source_paths = [
        entity_paths[seed] for seed in candidate.seed_entity_ids if seed in entity_paths
    ]
    sample_path = any(
        part in {"examples", "example", "docs_src", "tests", "test", "fixtures"}
        for path in source_paths
        for part in path.split("/")
    )
    return (
        PRIORITY_ORDER[candidate.category],
        project_paths[candidate.project_id],
        sample_path,
        min(source_paths, default=""),
        candidate.id,
    )


def build_investigation_candidates(
    tools: RepositoryToolset, limits: PlanningLimits | None = None
) -> CandidateCatalog:
    limits = limits or PlanningLimits()
    snapshot = tools.accessible_snapshot
    project_paths = {project.id: project.path for project in snapshot.projects}
    entity_paths = entity_source_paths(snapshot)
    files = {source.id: source for source in snapshot.files}
    evidence_paths = {record.id: record.path for record in snapshot.evidence}
    candidates = []

    def add(project_id, category, identity, seeds, description, limitations=()):
        unique_seeds = tuple(sorted(set(seeds)))
        if len(unique_seeds) > limits.max_seed_entities:
            limitations = (
                *limitations,
                f"Only {limits.max_seed_entities} of {len(unique_seeds)} structural seeds are offered; enumerate remaining entities with tools.",
            )
        candidates.append(
            InvestigationCandidate(
                id=create_identifier("candidate", project_id, category, identity),
                project_id=project_id,
                category=category,
                seed_entity_ids=unique_seeds[: limits.max_seed_entities],
                description=description,
                limitations=tuple(limitations),
            )
        )

    feasible_projects = set()
    for project in sorted(snapshot.projects, key=lambda project: project.path):
        members = [
            source for source in snapshot.files if source.project_id == project.id
        ]
        if members:
            feasible_projects.add(project.id)
        limitations = (
            []
            if members
            else ["No technical source/configuration is accessible for this project."]
        )
        if any(
            part
            in {"examples", "example", "tests", "test", "fixtures", "tools", "tooling"}
            for part in project.path.split("/")
        ):
            limitations.append(
                "Path convention suggests an example, test, or tooling unit; its role requires investigation."
            )
        if snapshot.coverage.unsupported_source_languages:
            limitations.append(
                "Deep parsing is unavailable for some detected languages; source inspection may be required."
            )
        add(
            project.id,
            "project_orientation",
            project.path,
            (project.id,),
            f"Classify project at {project.path}: {project.name}; ecosystem={project.ecosystem}; accessible technical files={len(members)}. Its application/package role is not established.",
            limitations,
        )

    groups = defaultdict(list)
    for entrypoint in snapshot.entrypoints:
        paths = [evidence_paths[identifier] for identifier in entrypoint.evidence_ids]
        path = (
            files[entrypoint.file_id].path
            if entrypoint.file_id in files
            else min(paths, default="configuration")
        )
        project_path = project_paths[entrypoint.project_id]
        relative_path = path if project_path == "." else path[len(project_path) + 1 :]
        sample_entrypoint = any(
            part in {"examples", "example", "docs_src", "tests", "test", "fixtures"}
            for part in relative_path.split("/")[:-1]
        )
        category = (
            "representative_flow"
            if entrypoint.kind in ("http_endpoint", "framework_page")
            or sample_entrypoint
            else "startup"
        )
        groups[(entrypoint.project_id, category, entrypoint.kind, path)].append(
            entrypoint
        )
    for (project_id, category, kind, path), entrypoints in sorted(groups.items()):
        add(
            project_id,
            category,
            (kind, path),
            (entrypoint.id for entrypoint in entrypoints),
            f"Inspect {len(entrypoints)} {kind} entrypoint(s) associated with {path}. Similar structural locations are grouped; behavior and runtime use remain unverified.",
        )

    # Public top-level definitions provide library investigation seeds even when
    # the entrypoint extractor does not recognize a public API convention.
    public_symbols = defaultdict(list)
    test_paths = {
        path for configuration in snapshot.testing for path in configuration.file_paths
    }
    for symbol in snapshot.symbols:
        source = files[symbol.file_id]
        if (
            symbol.parent_symbol_id is None
            and not symbol.name.startswith("_")
            and source.path not in test_paths
        ):
            public_symbols[(symbol.project_id, source.path)].append(symbol)
    for (project_id, path), symbols in sorted(public_symbols.items()):
        add(
            project_id,
            "representative_flow",
            ("public_definitions", path),
            (symbol.id for symbol in symbols),
            f"Inspect {len(symbols)} top-level definition(s) in {path}; public API status and functional responsibility require source investigation.",
        )

    incoming = defaultdict(set)
    for relationship in snapshot.relationships:
        if relationship.source_id in files and relationship.target_id in files:
            incoming[relationship.target_id].add(relationship.source_id)
    for file_id, sources in sorted(incoming.items()):
        if len(sources) >= 2:
            source = files[file_id]
            add(
                source.project_id,
                "shared_component_or_integration",
                ("shared_file", source.path),
                (file_id,),
                f"{source.path} is referenced by {len(sources)} distinct source files. Import fan-in is a discovery lead, not proof of functional importance.",
            )
    for integration in sorted(snapshot.infrastructure, key=lambda record: record.id):
        add(
            integration.project_id,
            "shared_component_or_integration",
            integration.id,
            (integration.id,),
            f"Inspect {integration.kind} record {integration.name}; detection={integration.detection}. Verify actual usage and state handling.",
        )

    ordered = tuple(
        sorted(
            candidates,
            key=lambda candidate: candidate_sort_key(
                candidate, project_paths, entity_paths
            ),
        )
    )
    # Offer orientation first, then round-robin across projects within each tier.
    offered = []
    for category in PRIORITY_ORDER:
        queues = defaultdict(list)
        for candidate in ordered:
            if (
                candidate.category == category
                and candidate.project_id in feasible_projects
            ):
                queues[candidate.project_id].append(candidate)
        while any(queues.values()) and len(offered) < limits.max_offered_candidates:
            for project_id in sorted(queues, key=project_paths.get):
                if queues[project_id] and len(offered) < limits.max_offered_candidates:
                    offered.append(queues[project_id].pop(0).id)
    return CandidateCatalog(ordered, tuple(offered))


def prioritize_objectives(
    objectives: tuple[InvestigationObjective, ...],
    project_paths: dict[str, str],
    entity_paths: dict[str, str] | None = None,
) -> tuple[InvestigationObjective, ...]:
    """Ordered tiers, project diversity, novel seeds, effort, and stable ties."""
    result = []
    seen_seeds = set()
    project_counts = Counter()
    remaining = list(objectives)
    entity_paths = entity_paths or {}

    def structural_seeds(objective):
        return {entity_paths.get(seed, seed) for seed in objective.seed_entity_ids}

    while remaining:
        blocked = {
            identifier
            for objective in remaining
            for identifier in objective.blocked_investigation_ids
        }
        eligible = [objective for objective in remaining if objective.id not in blocked]
        if not eligible:
            raise ValueError("Follow-up blocking dependencies contain a cycle.")
        selected = min(
            eligible,
            key=lambda objective: (
                PRIORITY_ORDER[objective.priority_tier],
                (0, project_paths[objective.project_id])
                if objective.priority_tier == "project_orientation"
                else (1, project_counts[objective.project_id]),
                any(
                    part
                    in {"examples", "example", "docs_src", "tests", "test", "fixtures"}
                    for path in structural_seeds(objective)
                    for part in path.split("/")
                ),
                -len(structural_seeds(objective) - seen_seeds),
                EFFORT_ORDER[objective.estimated_effort],
                project_paths[objective.project_id],
                objective.id,
            ),
        )
        remaining.remove(selected)
        result.append(selected)
        seen_seeds.update(structural_seeds(selected))
        project_counts[selected.project_id] += 1
    return tuple(result)


def normalized_text(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def objective_signature(objective: InvestigationObjective):
    return (
        objective.project_id,
        tuple(sorted(objective.seed_entity_ids)),
        tuple(sorted(objective.report_sections)),
        normalized_text(objective.objective),
    )


def validate_and_prioritize_plan(
    tools: RepositoryToolset, catalog: CandidateCatalog, proposal: InvestigationProposal
) -> InvestigationPlan:
    candidate_index = {candidate.id: candidate for candidate in catalog.candidates}
    offered = set(catalog.offered_candidate_ids)
    project_paths = {
        project.id: project.path for project in tools.accessible_snapshot.projects
    }
    assigned = {}
    signatures = {}
    objectives = []
    duplicate_ids = []
    for item in proposal.investigations:
        objective = item.objective
        if objective.origin_finding_ids or objective.blocked_investigation_ids:
            raise ValueError(
                "Initial objectives cannot claim prior findings or blockers."
            )
        if any(identifier not in offered for identifier in item.candidate_ids):
            raise ValueError("Objectives must refer to offered candidates only.")
        candidates = [candidate_index[identifier] for identifier in item.candidate_ids]
        if any(
            candidate.project_id != objective.project_id
            or candidate.category != objective.priority_tier
            for candidate in candidates
        ):
            raise ValueError(
                "Grouped candidates must share the objective project and priority tier."
            )
        seeds = {seed for candidate in candidates for seed in candidate.seed_entity_ids}
        if not set(objective.seed_entity_ids) <= seeds:
            raise ValueError("Objective seeds must come from its offered candidates.")
        signature = objective_signature(objective)
        if signature in signatures:
            duplicate_ids.append(objective.id)
            continue
        if any(identifier in assigned for identifier in item.candidate_ids):
            raise ValueError(
                "A candidate cannot belong to multiple distinct objectives."
            )
        if objective.id in {previous.id for previous in objectives}:
            raise ValueError("Objective identifiers must be unique.")
        signatures[signature] = objective.id
        objectives.append(objective)
        assigned.update({identifier: objective.id for identifier in item.candidate_ids})

    omissions = {}
    for omission in proposal.omissions:
        if (
            omission.candidate_id not in offered
            or omission.candidate_id in assigned
            or omission.candidate_id in omissions
        ):
            raise ValueError(
                "Omissions must refer to distinct, unassigned offered candidates."
            )
        omissions[omission.candidate_id] = omission

    budget = tools.context.input.budget.max_investigations
    required = [
        candidate
        for candidate in catalog.candidates
        if candidate.id in offered and candidate.category == "project_orientation"
    ]
    required.sort(key=lambda candidate: project_paths[candidate.project_id])
    for candidate in required[:budget]:
        if candidate.id not in assigned:
            raise ValueError(
                "Each selected project requires an orientation objective before functional exploration."
            )
    ordered = prioritize_objectives(
        tuple(objectives), project_paths, entity_source_paths(tools.accessible_snapshot)
    )
    accepted = ordered[:budget]
    if not accepted:
        raise ValueError(
            "The proposal must schedule at least one feasible investigation."
        )
    selected_ids = {objective.id for objective in accepted}
    oriented_projects = {
        objective.project_id
        for objective in accepted
        if objective.priority_tier == "project_orientation"
    }
    if any(objective.project_id not in oriented_projects for objective in accepted):
        raise ValueError(
            "Selected functional objectives require project orientation coverage."
        )
    decisions = []
    for candidate in catalog.candidates:
        objective_id = assigned.get(candidate.id)
        omission = omissions.get(candidate.id)
        if objective_id in selected_ids:
            grouped_count = sum(value == objective_id for value in assigned.values())
            disposition = "grouped" if grouped_count > 1 else "accepted"
            reason = next(
                objective.selection_reason
                for objective in accepted
                if objective.id == objective_id
            )
            if duplicate_ids:
                reason += " Equivalent duplicate proposals were removed."
        elif objective_id is not None:
            disposition, reason = (
                "deferred",
                "Investigation limit reached after coverage and priority ordering.",
            )
            objective_id = None
        elif candidate.id not in offered:
            disposition, reason = (
                "deferred",
                "Not offered because of accessible-content or candidate/prompt limits.",
            )
        elif omission is not None:
            disposition, reason = omission.disposition, omission.reason
        else:
            disposition, reason = (
                "deferred",
                "Not selected by the model for this bounded plan.",
            )
        decisions.append(
            PlanningDecision(
                id=create_identifier(
                    "planning_decision", candidate.id, disposition, objective_id
                ),
                candidate_id=candidate.id,
                disposition=disposition,
                reason=reason,
                investigation_id=objective_id,
            )
        )
    plan = InvestigationPlan(
        candidates=catalog.candidates, objectives=accepted, decisions=tuple(decisions)
    )
    tools.context.validate_plan(plan)
    return plan


def select_deterministic_plan(
    tools: RepositoryToolset, limits=None
) -> InvestigationPlan:
    """Choose a bounded functional scope; every heuristic and omission is auditable."""
    catalog = build_investigation_candidates(tools, limits)
    snapshot = tools.accessible_snapshot
    paths = entity_source_paths(snapshot)
    project_paths = {project.id: project.path for project in snapshot.projects}
    files = {source.id: source for source in snapshot.files}
    incoming = Counter(
        rel.target_id for rel in snapshot.relationships if rel.target_id in files
    )
    projects_with_files = {source.project_id for source in snapshot.files}
    candidates = [
        candidate
        for candidate in catalog.candidates
        if candidate.project_id in projects_with_files
    ]

    def rank(candidate):
        locations = {paths[seed] for seed in candidate.seed_entity_ids if seed in paths}
        sample = any(
            part in {"tests", "test", "examples", "example", "docs_src", "fixtures"}
            for path in locations
            for part in path.split("/")
        )
        core_names = {
            "main",
            "app",
            "application",
            "applications",
            "views",
            "routes",
            "router",
            "routers",
            "index",
            "page",
            "core",
            "__init__",
            "wsgi",
            "asgi",
        }
        core = any(
            PurePosixPath(path).stem.casefold() in core_names for path in locations
        )
        scaffold = any(
            PurePosixPath(path).stem.casefold()
            in {"layout", "_app", "_document", "loading", "error", "not-found"}
            for path in locations
        )
        fan_in = max(
            (
                incoming[file_id]
                for file_id, source in files.items()
                if source.path in locations
            ),
            default=0,
        )
        return (
            sample,
            scaffold,
            not core,
            -fan_in,
            min(locations, default=""),
            candidate.id,
        )

    selected = []
    max_targets = tools.context.input.budget.max_investigations
    oriented = set()
    for candidate in sorted(
        (item for item in candidates if item.category == "project_orientation"),
        key=lambda item: project_paths[item.project_id],
    ):
        if len(selected) < max_targets:
            selected.append(candidate)
            oriented.add(candidate.project_id)
    # Round-robin projects; at most one startup, then two diverse representative
    # flows, then one integration/shared unit before admitting further targets.
    used_paths = set()
    used_areas = set()

    def area(path):
        parts = list(PurePosixPath(path).parts)
        while parts and parts[0] in {"src", "app", "pages", "lib", "source"}:
            parts.pop(0)
        return parts[0] if len(parts) > 1 else path

    for category, rounds in (
        ("startup", 1),
        ("representative_flow", 2),
        ("shared_component_or_integration", 1),
    ):
        for _ in range(rounds):
            for project_id in sorted(oriented, key=project_paths.get):
                eligible = [
                    item
                    for item in candidates
                    if item.project_id == project_id
                    and item.category == category
                    and item not in selected
                    and not (
                        {paths[seed] for seed in item.seed_entity_ids if seed in paths}
                        & used_paths
                    )
                ]
                if eligible and len(selected) < max_targets:
                    candidate = min(
                        eligible,
                        key=lambda item: (
                            bool(
                                {
                                    area(paths[seed])
                                    for seed in item.seed_entity_ids
                                    if seed in paths
                                }
                                & used_areas
                            ),
                            rank(item),
                        ),
                    )
                    selected.append(candidate)
                    used_paths.update(
                        paths[seed]
                        for seed in candidate.seed_entity_ids
                        if seed in paths
                    )
                    if category == "representative_flow":
                        used_areas.update(
                            area(paths[seed])
                            for seed in candidate.seed_entity_ids
                            if seed in paths
                        )
    if not selected:
        raise ValueError("No accessible technical project can be investigated.")
    objectives = []
    section_map = {
        "project_orientation": ("project_identification", "functional_components"),
        "startup": ("functional_components", "main_flows"),
        "representative_flow": (
            "functional_components",
            "main_flows",
            "component_relationships",
            "integrations_and_state",
            "testing",
        ),
        "shared_component_or_integration": (
            "functional_components",
            "integrations_and_state",
        ),
    }
    for candidate in selected:
        seeds = list(candidate.seed_entity_ids)
        if candidate.category == "project_orientation":
            members = [
                source
                for source in snapshot.files
                if source.project_id == candidate.project_id
            ]
            manifests = [
                source
                for source in members
                if PurePosixPath(source.path).name
                in {"package.json", "pyproject.toml", "setup.py", "requirements.txt"}
            ]
            seeds.extend(
                source.id
                for source in sorted(manifests, key=lambda item: item.path)[:2]
            )
            lead = min(
                (
                    item
                    for item in candidates
                    if item.project_id == candidate.project_id
                    and item.category in {"startup", "representative_flow"}
                ),
                key=rank,
                default=None,
            )
            if lead:
                seeds.extend(lead.seed_entity_ids[:2])
                for seed in lead.seed_entity_ids[:2]:
                    source_path = paths.get(seed)
                    seeds.extend(
                        file_id
                        for file_id, source in files.items()
                        if source.path == source_path
                    )
        objectives.append(
            InvestigationObjective(
                id=create_identifier("investigation", "deterministic", candidate.id),
                project_id=candidate.project_id,
                objective=candidate.description,
                seed_entity_ids=tuple(dict.fromkeys(seeds)),
                questions=(
                    "What responsibility and behavior can inspected implementation establish?",
                    "Which calls, state, integrations, or runtime selections remain unresolved?",
                ),
                report_sections=section_map[candidate.category],
                selection_reason="Deterministic project coverage, role/path heuristic, source diversity, and import fan-in; functional importance remains unverified.",
                priority_tier=candidate.category,
                expected_deliverable="Source-backed responsibilities and scoped flows, or explicit unanswered questions.",
                completion_criteria=(
                    "Inspect relevant implementation and follow material calls; preserve unresolved wiring and omissions.",
                ),
            )
        )
    by_candidate = {
        candidate.id: objective.id
        for candidate, objective in zip(selected, objectives, strict=True)
    }
    decisions = tuple(
        PlanningDecision(
            id=create_identifier("planning_decision", "deterministic", candidate.id),
            candidate_id=candidate.id,
            disposition="accepted" if candidate.id in by_candidate else "deferred",
            investigation_id=by_candidate.get(candidate.id),
            reason="Selected by deterministic coverage/diversity policy."
            if candidate.id in by_candidate
            else "Outside the bounded deterministic scope; no functional conclusion was drawn.",
        )
        for candidate in catalog.candidates
    )
    plan = InvestigationPlan(
        candidates=catalog.candidates, objectives=tuple(objectives), decisions=decisions
    )
    tools.context.validate_plan(plan)
    return plan


def admit_followups(
    tools: RepositoryToolset,
    plan: InvestigationPlan,
    findings: tuple[InvestigationResult, ...],
    proposals: tuple[InvestigationObjective, ...],
    *,
    usage: BudgetUsage | None = None,
) -> InvestigationPlan:
    """Admit verified-origin follow-ups; inherit unfinished blocker priority."""
    finding_index = {finding.id: finding for finding in findings}
    if len(finding_index) != len(findings):
        raise ValueError("Accepted finding identifiers must be unique.")
    tools.context.validate_plan(plan, known_finding_ids=tuple(finding_index))
    objectives = {objective.id: objective for objective in plan.objectives}
    finished = {
        finding.investigation_id
        for finding in findings
        if finding.status == "completed"
    }
    paths = {project.id: project.path for project in tools.accessible_snapshot.projects}
    all_entities = {
        record.id
        for collection in (
            tools.accessible_snapshot.projects,
            tools.accessible_snapshot.files,
            tools.accessible_snapshot.symbols,
            tools.accessible_snapshot.entrypoints,
            tools.accessible_snapshot.infrastructure,
            tools.accessible_snapshot.dependencies,
        )
        for record in collection
    }
    candidates = list(plan.candidates)
    decisions = list(plan.decisions)
    signatures = {objective_signature(objective) for objective in plan.objectives}
    for proposal in proposals:
        if not proposal.origin_finding_ids or any(
            identifier not in finding_index
            for identifier in proposal.origin_finding_ids
        ):
            raise ValueError("Follow-ups require accepted origin findings.")
        if any(
            finding_index[identifier].investigation_id not in objectives
            for identifier in proposal.origin_finding_ids
        ):
            raise ValueError("Origin findings must belong to the accepted plan.")
        if not set(proposal.seed_entity_ids) <= all_entities:
            raise ValueError("Follow-up seeds must be accessible in this checkout.")
        blockers = proposal.blocked_investigation_ids
        if any(
            identifier not in objectives
            or identifier in finished
            or identifier == proposal.id
            for identifier in blockers
        ):
            raise ValueError(
                "Blockers must refer to unfinished accepted investigations."
            )
        effective_tier = min(
            (
                proposal.priority_tier,
                *(objectives[identifier].priority_tier for identifier in blockers),
            ),
            key=PRIORITY_ORDER.get,
        )
        objective = proposal.model_copy(update={"priority_tier": effective_tier})
        candidate = InvestigationCandidate(
            id=create_identifier("candidate", "followup", proposal.id),
            project_id=proposal.project_id,
            category=effective_tier,
            seed_entity_ids=proposal.seed_entity_ids,
            description=proposal.objective,
        )
        previous_candidate = next(
            (previous for previous in candidates if previous.id == candidate.id), None
        )
        if previous_candidate is not None:
            if previous_candidate != candidate:
                raise ValueError("A replayed follow-up cannot rewrite its candidate.")
            continue
        if objective.priority_tier != "project_orientation" and not any(
            previous.project_id == objective.project_id
            and previous.priority_tier == "project_orientation"
            for previous in objectives.values()
        ):
            raise ValueError(
                "Follow-ups require orientation coverage for their project."
            )
        signature = objective_signature(objective)
        if proposal.id in objectives or signature in signatures:
            disposition, reason = "rejected", "Duplicate follow-up objective."
        elif (
            (
                usage is not None
                and (
                    usage.token_budget_exhausted
                    or usage.accounted_tokens
                    + tools.context.input.budget.max_output_tokens_per_call
                    >= tools.context.input.budget.max_total_tokens
                )
            )
            or tools.context.elapsed_seconds
            >= tools.context.input.budget.max_elapsed_seconds
            or (
                usage is not None
                and usage.model_calls
                >= tools.context.input.budget.max_model_calls
                - tools.context.input.budget.reserved_report_model_calls
            )
        ):
            disposition, reason = (
                "deferred",
                "Execution budget is reserved or exhausted before follow-up investigation.",
            )
        elif len(objectives) >= tools.context.input.budget.max_investigations:
            disposition, reason = (
                "deferred",
                "Investigation budget cannot admit another follow-up.",
            )
        else:
            disposition, reason = "accepted", proposal.selection_reason
            objectives[objective.id] = objective
            signatures.add(signature)
        decision = PlanningDecision(
            id=create_identifier("planning_decision", candidate.id, disposition),
            candidate_id=candidate.id,
            disposition=disposition,
            reason=reason,
            investigation_id=objective.id if disposition == "accepted" else None,
        )
        # Replayed follow-up proposals must not append conflicting audit records.
        if candidate.id not in {previous.id for previous in candidates}:
            candidates.append(candidate)
            decisions.append(decision)
    result = InvestigationPlan(
        candidates=tuple(candidates),
        objectives=prioritize_objectives(
            tuple(objectives.values()),
            paths,
            entity_source_paths(tools.accessible_snapshot),
        ),
        decisions=tuple(decisions),
    )
    tools.context.validate_plan(result, known_finding_ids=tuple(finding_index))
    return result

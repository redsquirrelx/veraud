"""Local planning-ranking checks for ArchitectureBoundaryAgentV2."""

from types import SimpleNamespace

from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.planning import (
    _documentary_profile,
    _rank_documentary_tasks,
    balance_candidates,
    planning_diagnostics,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
    BoundaryInvestigation,
    StructuralQuery,
    StructuralRelationship,
    StructuralSignal,
)


def relation(task):
    return task.structural_signal.relationships


def make_task(task_id, kind="documented_boundary", priority="medium", basis="indexed",
              scope=None, claim_ids=None, relations=None, question=None):
    return BoundaryInvestigation(
        id=task_id,
        priority=priority,
        scope=scope or [f"{task_id}.ts"],
        project_ids=["project"],
        scope_kind="internal",
        structural_signal=StructuralSignal(
            kind=kind, basis=basis,
            observed=["Observed."],
            inference="Inspect, do not infer a finding.",
            relationships=relations or [],
        ),
        question=question or "Do the actual dependency mechanisms respect the boundary?",
        evidence_needed=["Inspect the mechanism."],
        investigation_strategy=[StructuralQuery(tool="find_symbols", arguments={"file_path": "x"})],
        completion_condition="Bounded inspection or an explicit limitation.",
        document_claim_ids=claim_ids or [],
    )


def record(constraint="prohibited", basis="exact", subject_paths=None, unresolved=()):
    return SimpleNamespace(
        status="applicable",
        claim=SimpleNamespace(
            constraint=constraint,
            subject="app/api",
            statement="app.api must not import Prisma.",
            related_subjects=["Prisma"],
        ),
        mapping_basis=basis,
        subject_paths=subject_paths or [],
        unresolved_references=list(unresolved),
        unrepresented_paths=[],
        scope_paths=[*(subject_paths or []), "lib/prisma.ts"],
        excluded_paths=[],
        owner_paths={"Prisma": ["lib/prisma.ts"]},
        boundary_family="dependency",
        portions=[],
        opportunity_ids=[],
    )


def priority_after(task, claims):
    return _rank_documentary_tasks([task], claims)[0].priority


def test_strong_documentary_prohibition_beats_generic_exploration():
    strong = make_task("strong-doc", relations=[
        StructuralRelationship(id="rel-source", source_id="file-source", target_id="file-target",
                               source_path="app/api/route.ts", target_path="lib/prisma.ts", kind="import"),
    ], scope=["app/api/route.ts", "lib/prisma.ts"], claim_ids=["strong"])
    claims = {"strong": record(subject_paths=["app/api/route.ts"])}
    assert _documentary_profile(strong, claims)["tier"] == "strong"
    assert priority_after(strong, claims) == "high"
    generic = make_task("generic", kind="direction", priority="medium", basis="inferred",
                        scope=["app/api/route.ts"])
    selected = balance_candidates([strong, generic], {"strong-doc": ["project"], "generic": ["project"]}, 1)
    assert [task.id for task in selected] == ["strong-doc"]


def test_corroborated_structure_remains_above_ambigous_documentation():
    weak = make_task("weak-doc", scope=["app/api/route.ts", "lib/prisma.ts"], claim_ids=["weak"])
    weak_claims = {"weak": record(constraint="allowed", basis="ambiguous",
                                  subject_paths=["app/api/route.ts"])}
    assert priority_after(weak, weak_claims) == "low"
    corroborated = make_task(
        "corroborated", kind="cycle", priority="medium", basis="corroborated",
        scope=["app/api/route.ts"], relations=[
            StructuralRelationship(id="rel-cycle", source_id="a", target_id="b", source_path="app/api/route.ts",
                                   target_path="lib/prisma.ts", kind="import")])
    selected = balance_candidates([weak, corroborated], {"weak-doc": ["project"], "corroborated": ["project"]}, 1)
    assert [task.id for task in selected] == ["corroborated"]


def test_equivalent_obligations_do_not_acaparen_the_menu():
    duplicate = make_task("doc-a", claim_ids=["same-claim"], scope=["app/api/a.ts", "lib/prisma.ts"])
    copy = make_task("doc-b", claim_ids=["same-claim"], scope=["app/api/b.ts", "lib/prisma.ts"])
    other = make_task("direction", kind="direction", priority="medium", basis="indexed",
                      scope=["app/services/order.ts", "lib/prisma.ts"])
    selected = balance_candidates([duplicate, copy, other],
                                  {"doc-a": ["project"], "doc-b": ["project"], "direction": ["project"]}, 2)
    assert [task.id for task in selected] == ["doc-a", "direction"]


def test_balancing_remains_project_aware_and_does_not_add_model_tasks():
    first = make_task("first", kind="direction", priority="high", scope=["west/a.ts"])
    second = make_task("second", kind="direction", priority="high", scope=["east/a.ts"])
    selected = balance_candidates([first, second], {"first": ["west"], "second": ["east"]}, 2)
    assert {task.id for task in selected} == {"first", "second"}
    explicit = balance_candidates([first, second], {"first": ["west"], "second": ["east"]}, 2, preferred=[second])
    assert [task.id for task in explicit] == ["second"]
    assert balance_candidates([first, second], {"first": ["west"], "second": ["east"]}, 2, preferred=[]) == []


def test_documentary_diagnostics_reports_strong_exclusion():
    strong = make_task("strong-doc", relations=[
        StructuralRelationship(id="rel-route", source_id="file-route", target_id="file-prisma",
                               source_path="app/api/route.ts", target_path="lib/prisma.ts", kind="import"),
    ], scope=["app/api/route.ts", "lib/prisma.ts"], claim_ids=["strong"])
    strong = _rank_documentary_tasks([strong], {"strong": record(subject_paths=["app/api/route.ts"])})[0]
    diagnostics = planning_diagnostics(
        {"_task_projects": {"strong-doc": ["project"]}, "project_coverage": [],
         "_document_claims": {"strong": record(subject_paths=["app/api/route.ts"])},
         "_documentary_candidates": [strong]},
        [], [], [],
    )["documentary_ranking"]
    assert diagnostics["strong_generated"] == 1
    assert diagnostics["strong_in_menu"] == 0
    assert diagnostics["strong_omitted_by_menu_limit"] == 1
    assert diagnostics["strong_omitted_ids"] == ["strong-doc"]
    assert diagnostics["strong_exclusion_reasons"]["strong-doc"]["normative"] == "strong"


def test_global_pending_routes_do_not_downgrade_local_route_relation():
    subjects = [
        "app/api/customers/route.ts",
        *(f"app/api/route-{index}.ts" for index in range(91)),
    ]
    unrepresented = [f"app/api/pending-{index}.ts" for index in range(13)]
    customers = make_task(
        "customers", relations=[
            StructuralRelationship(
                id="rel-customers", source_id="file-customers", target_id="file-prisma",
                source_path="app/api/customers/route.ts", target_path="lib/prisma.ts", kind="import"),
        ], scope=["app/api/customers/route.ts", "lib/prisma.ts"], claim_ids=["route-prohibition"])
    account_record = record(subject_paths=subjects, unresolved=("docs/rules.md",))
    account_record.unrepresented_paths = unrepresented
    account_record.scope_paths = [*subjects, "lib/prisma.ts"]
    claims = {"route-prohibition": account_record}
    profile = _documentary_profile(customers, claims)
    assert profile["global_partial"] is True
    assert profile["local_partial"] is False
    assert profile["tier"] == "strong"
    assert priority_after(customers, claims) == "high"


def test_destination_overlap_without_regulated_origin_is_not_local():
    destination_only = make_task(
        "other", relations=[
            StructuralRelationship(
                id="rel-other", source_id="file-other", target_id="file-prisma",
                source_path="app/services/order.ts", target_path="lib/prisma.ts", kind="import"),
        ], scope=["app/services/order.ts", "lib/prisma.ts"], claim_ids=["route-prohibition"])
    claims = {"route-prohibition": SimpleNamespace(
        **vars(record(subject_paths=["app/api/customers/route.ts"])),
    )}
    assert _documentary_profile(destination_only, claims)["tier"] == "weak"


def test_allowed_service_permission_is_not_promoted_as_a_contradiction():
    allowed = make_task(
        "service-allowed", relations=[
            StructuralRelationship(
                id="rel-service", source_id="file-service", target_id="file-prisma",
                source_path="lib/services/order.ts", target_path="lib/prisma.ts", kind="import"),
        ], scope=["lib/services/order.ts", "lib/prisma.ts"], claim_ids=["service-permission"])
    claims = {"service-permission": record(
        constraint="allowed", subject_paths=["lib/services/order.ts"])}
    assert _documentary_profile(allowed, claims)["tier"] == "weak"
    assert priority_after(allowed, claims) == "low"


def test_explicit_obligation_without_a_relation_remains_a_coherent_probe():
    probe = make_task("no-relation", scope=["app/api/customers/route.ts", "lib/prisma.ts"],
                      claim_ids=["route-prohibition"])
    claims = {"route-prohibition": record(subject_paths=["app/api/customers/route.ts"])}
    assert _documentary_profile(probe, claims)["tier"] == "moderate"
    assert priority_after(probe, claims) == "medium"


def test_enriched_structural_probe_receives_local_documentary_priority():
    enriched = make_task(
        "enriched", kind="direction", relations=[
            StructuralRelationship(
                id="rel-enriched", source_id="file-route", target_id="file-prisma",
                source_path="app/api/customers/route.ts", target_path="lib/prisma.ts", kind="import"),
        ], scope=["app/api/customers/route.ts", "lib/prisma.ts"], claim_ids=["route-prohibition"])
    claims = {"route-prohibition": SimpleNamespace(
        **vars(record(subject_paths=["app/api/customers/route.ts"])),
    )}
    assert _rank_documentary_tasks([enriched], claims)[0].priority == "high"


def test_regression_routes_receive_strong_local_priority():
    for route in [
        "app/api/customers/route.ts",
        "app/api/accounts/[id]/route.ts",
        "app/api/cash-sessions/route.ts",
    ]:
        relation = make_task(
            route,
            relations=[
                StructuralRelationship(
                    id=f"rel-{route}", source_id=f"file-{route}", target_id="file-prisma",
                    source_path=route, target_path="lib/prisma.ts", kind="import"),
            ],
            scope=[route, "lib/prisma.ts"],
            claim_ids=["route-prohibition"],
        )
        claims = {"route-prohibition": SimpleNamespace(
            **vars(record(subject_paths=[route])),
        )}
        assert _documentary_profile(relation, claims)["tier"] == "strong"
        assert _rank_documentary_tasks([relation], claims)[0].priority == "high"



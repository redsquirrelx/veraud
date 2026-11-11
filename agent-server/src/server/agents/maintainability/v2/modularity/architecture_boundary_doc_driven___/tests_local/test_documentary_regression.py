"""Local documentary regression checks for ArchitectureBoundaryAgent.

Self-contained fixtures: they intentionally do not import the shared test
suite so this agent's directory stays the only place these checks live.
"""

from typing import get_args

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
    RetrievalCategory,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
    AuditRequest,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.documentation import (
    prepare_documentation,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.planning import (
    planning_diagnostics,
    prepare_planning,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.document_indexing import DocumentRecord, IndexReference
from server.services.document_indexing.service import identifier
from server.services.repository_analysis import RepositoryAnalysisService


def indexed_tools(tmp_path, contents):
    root = tmp_path / "repo"
    for name, content in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    snapshot = snapshot.model_copy(update={"repository": snapshot.repository.model_copy(update={"commit": "abc"})})
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_input_tokens_per_call=50_000))), workspace_root=tmp_path)


def claim(statement, subject="app/api", related=None, **updates):
    return KnowledgeClaim.model_validate({
        "category": "constraints", "subject": subject, "statement": statement,
        "related_subjects": related or [], "certainty": "explicit", "section_ids": ["s1"],
        "reasoning": "Obligación arquitectónica adoptada.",
        "constraint": "prohibited",
        "evidence": [{"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "Obligación documentada.\n"}],
        **updates,
    })


def context(tools, claims):
    snapshot = tools.accessible_snapshot
    index = IndexReference(index_id="index", repository_id=identifier(str(
        __import__("pathlib").Path(snapshot.repository.root_path).resolve())), commit=snapshot.repository.commit)
    return ArchitectureContextResult.model_validate({
        "document_index": index, "knowledge": claims, "knowledge_issues": [],
        "covered_categories": [], "pending_categories": list(get_args(RetrievalCategory)),
        "evaluated_categories": list(get_args(RetrievalCategory)), "coverage_assessment_status": "completed",
        "consulted_documents": [DocumentRecord(**index.model_dump(), path="docs/rules.md",
                                                content_hash="hash", line_count=10)],
        "section_paths": {"s1": "docs/rules.md"}, "validation_errors": [],
        "execution_status": "partial", "finalization_reason": "incomplete_coverage",
    })


def prepare(tools, source, limit=100):
    return prepare_planning(tools.accessible_snapshot, AuditRequest(documented_architecture=source),
                            limit=limit, check=lambda: None)


def docs(menu):
    return [task for task in menu if task.structural_signal.kind == "documented_boundary"]


def small_tools(tmp_path):
    return indexed_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "from .store import Store\nclass Api:\n    pass\n",
        "app/store.py": "from .api import Api\nclass Store:\n    pass\n",
    })


def test_alias_lib_prisma_resolves_to_indexed_file(tmp_path):
    tools = indexed_tools(tmp_path, {
        "src/lib/prisma.ts": "export const prisma = {};\n",
        "app/api/orders/route.ts": "export async function GET() {}\n",
    })
    rule = claim("app/api/orders/route.ts must not import @/lib/prisma directly.",
                 subject="app/api/orders/route.ts", related=["@/lib/prisma"])
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "applicable"
    assert "src/lib/prisma.ts" in record.scope_paths
    assert "app/api/orders/route.ts" in record.scope_paths
    assert docs(menu)


def test_next_parameterized_route_resolves(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/roles/[id]/route.ts": "export async function GET() {}\n",
    })
    rule = claim("Handlers in app/api/roles/[id]/route.ts must not import @/lib/prisma.",
                 subject="app/api/roles/[id]/route.ts")
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert "app/api/roles/[id]/route.ts" in record.scope_paths
    assert record.status == "applicable"


def test_next_brace_set_resolves_each_route(tmp_path):
    contents = {}
    for name in ("tables", "settings", "payment-methods", "roles"):
        contents[f"app/api/{name}/route.ts"] = "export async function GET() {}\n"
    tools = indexed_tools(tmp_path, contents)
    rule = claim("app/api/{tables,settings,payment-methods,roles}/route.ts must not import @/lib/prisma.",
                 subject="app/api/{tables,settings,payment-methods,roles}")
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    for name in ("tables", "settings", "payment-methods", "roles"):
        assert f"app/api/{name}/route.ts" in record.scope_paths


def test_next_handlers_do_not_map_to_python_routes(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/orders/route.ts": "export async function GET() {}\n",
        "src/lib/prisma.ts": "export const prisma = {};\n",
        "web/routes.py": "def routes():\n    pass\n",
        "web/__init__.py": "",
    })
    # The obligation governs the Next.js handlers themselves; mentioning
    # "routes"/"handlers" must not pull in the unrelated Python module.
    rule = claim("The routes handlers in app/api/orders/route.ts must not import @/lib/prisma.",
                 subject="app/api/orders/route.ts")
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert "web/routes.py" not in record.scope_paths
    assert "web/__init__.py" not in record.scope_paths
    assert "app/api/orders/route.ts" in record.scope_paths


def test_spanish_prohibition_and_direction_are_dependency_families(tmp_path):
    tools = small_tools(tmp_path)
    cases = [
        "Los handlers de app/api no deben importar implementaciones concretas de app/store.",
        "Se prohíbe que app.api dependa de app.store.",
        "app.api debe pasar por app.store únicamente.",
        "app.api → app.store: app.api debe pasar por app.store.",
    ]
    for statement in cases:
        rule = claim(statement, subject="app/api", related=["app/store"])
        _menu, inventory, _ = prepare(tools, context(tools, [rule]))
        record = next(iter(inventory["_document_claims"].values()))
        assert record.boundary_family == "dependency", statement
        assert record.status == "applicable", statement


def test_ambiguous_reference_preserves_resolved_ones(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "class Api:\n    pass\n",
        "app/store.py": "class Store:\n    pass\n",
        "src/shoplab/bootstrap.py": "def build(): pass\n",
        "legacy/shoplab/bootstrap.py": "def build(): pass\n",
    })
    rule = claim("app.api must not import shoplab/bootstrap.py implementations.",
                 subject="app/api", related=["shoplab/bootstrap.py"])
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "applicable"
    assert "app/api.py" in record.scope_paths
    assert record.unresolved_references  # ambiguous portion recorded, not verified
    assert docs(menu)


def test_multiproject_broad_claim_is_represented_per_subproject(tmp_path):
    tools = indexed_tools(tmp_path, {
        "wetapp/app/api.py": "class Api:\n    pass\n",
        "wetapp/app/store.py": "class Store:\n    pass\n",
        "pyapp/app/api.py": "class Api:\n    pass\n",
        "pyapp/app/store.py": "class Store:\n    pass\n",
    })
    snapshot = tools.accessible_snapshot
    files = {f.id: f for f in snapshot.files if f.path.startswith(("wetapp/", "pyapp/"))}
    projects = {key: ("wet" if f.path.startswith("wetapp/") else "py") for key, f in files.items()}
    rule = claim("wetapp.app and pyapp.app must not import implementations directly.",
                 subject="wetapp.app", related=["pyapp.app"])
    source = context(tools, [rule])
    tasks, records, _, _ = prepare_documentation(
        snapshot, AuditRequest(documented_architecture=source), files, set(files), projects, check=lambda: None)
    assert tasks
    assert len({task.project_ids[0] for task in tasks if task.project_ids}) >= 2
    assert all(task.scope and all(
        (path.startswith("wetapp/") and task.project_ids == ["wet"])
        or (path.startswith("pyapp/") and task.project_ids == ["py"])
        for path in task.scope) for task in tasks)
    diagnostics = planning_diagnostics(
        {"_task_projects": {t.id: t.project_ids for t in tasks}, "project_coverage": [],
         "_document_claims": records, "_documentary_candidates": tasks,
         "documentary_diagnostics": {"received": 1, "context_status": "compatible"}},
        tasks, tasks, tasks)["documentation"]
    assert diagnostics["grouped"] >= 1 and diagnostics["selected"] >= 1


def test_small_shoplab_behavior_is_preserved(tmp_path):
    tools = small_tools(tmp_path)
    rule = claim("app.api must not depend on app.store implementations.",
                 subject="app.api", related=["app.store"])
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    assert docs(menu)
    assert docs(menu)[0].scope == ["app/api.py", "app/store.py"]
    diagnostics = planning_diagnostics(inventory, menu, menu, menu)["documentation"]
    assert diagnostics["applicable"] == diagnostics["selected"] == 1
    assert not diagnostics["pending_claim_ids"]
    assert diagnostics["investigated"] == 0


def test_route_to_prisma_is_oriented_from_the_regulated_origin(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { run } from '../service';\nexport async function GET() { return run(); }\n",
        "app/service.ts": "import { prisma } from '@/lib/prisma';\nexport function run() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
    })
    rule = claim("app/api/route.ts → app/service.ts → lib/prisma.ts: app/api/route.ts debe pasar por @/lib/prisma.",
                 subject="app/api/route.ts", related=["app/service.ts", "@/lib/prisma"])
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    task = docs(menu)[0]
    # The regulated origin leads the scope; the destination never becomes it.
    assert task.scope[0] == "app/api/route.ts"
    assert "lib/prisma.ts" in task.scope
    strategy = {query.tool: query.arguments for query in task.investigation_strategy}
    route_id = next(f.id for f in tools.accessible_snapshot.files if f.path == "app/api/route.ts")
    assert strategy["list_relationships"]["source_id"] == route_id
    assert strategy["find_symbols"]["file_path"] == "app/api/route.ts"
    record = next(iter(inventory["_document_claims"].values()))
    assert record.portions and record.portions[0].relationship_ids


def test_brace_rule_excludes_purchases_but_glob_includes_it(tmp_path):
    contents = {}
    for name in ("tables", "settings", "payment-methods", "roles", "purchases"):
        contents[f"app/api/{name}/route.ts"] = "export async function GET() {}\n"
    contents["src/lib/prisma.ts"] = "export const prisma = {};\n"
    tools = indexed_tools(tmp_path, contents)
    restricted = claim("app/api/{tables,settings,payment-methods,roles} must not import @/lib/prisma.",
                       subject="app/api/{tables,settings,payment-methods,roles}")
    _menu, inventory, _ = prepare(tools, context(tools, [restricted]))
    record = next(iter(inventory["_document_claims"].values()))
    assert "app/api/purchases/route.ts" not in record.scope_paths
    broad = claim("app/api/** must not import @/lib/prisma.", subject="app/api/**")
    _menu, other, _ = prepare(tools, context(tools, [broad]))
    broad_record = next(iter(other["_document_claims"].values()))
    assert "app/api/purchases/route.ts" in broad_record.scope_paths


def test_warning_and_importes_are_not_code_owners(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "export async function GET() {}\n",
        "app/warning.ts": "export function warning() {}\n",
        "src/lib/prisma.ts": "export const prisma = {};\n",
    })
    rule = claim("app/api/route.ts must not import @/lib/prisma. A warning is shown when los importes are invalid.",
                 subject="app/api/route.ts")
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert "app/warning.ts" not in record.scope_paths
    assert "src/lib/prisma.ts" in record.scope_paths
    money = claim("Los importes deben ser positivos en app/api/route.ts.",
                  subject="app/api/route.ts", constraint="unspecified")
    _menu, other, _ = prepare(tools, context(tools, [money]))
    money_record = next(iter(other["_document_claims"].values()))
    assert money_record.boundary_family is None and money_record.status == "not_applicable"


def test_standalone_exception_does_not_seed_its_own_investigation(tmp_path):
    tools = small_tools(tmp_path)
    exception = claim("Exception: app.api may import app.store internals.",
                      subject="app.api", related=["app.store"], constraint="exception")
    menu, inventory, _ = prepare(tools, context(tools, [exception]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "applicable" and not docs(menu)


def _turn_with_conclusion(**overrides):
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryInvestigationTurn,
    )
    payload = {"action": "close", "queries": [], "conclusion": {
        "investigation_id": "inv-1", "status": "inconclusive",
        "summary": "No source delivered.", "justification": "No source was available.",
        "components": [], "evidence_ids": [], "claim_assessments": [], "limitations": []}}
    payload["conclusion"].update(overrides)
    return BoundaryInvestigationTurn.model_validate(payload)


def _repair_exec(turn):
    import logging

    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
        BoundaryExecution,
    )
    execution = BoundaryExecution.__new__(BoundaryExecution)
    execution._invalid_turn = turn
    execution._citation_error = "inconclusive_requires_limitations"
    execution.logger = logging.getLogger("test-repair")
    return execution


def test_repair_adds_only_missing_limitations_and_preserves_conclusion():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryCitationPatch,
        BoundaryCitationRepair,
    )
    assessment = {"claim_id": "document_claim_x", "status": "inconclusive",
        "rationale": "No source delivered.", "code_evidence_ids": [], "scope_paths": [],
        "exceptions_examined": [], "limitations": ["Local scope only."], "assessment_origin": "investigator"}
    turn = _turn_with_conclusion(claim_assessments=[assessment])
    repair = BoundaryCitationRepair(action="patch", corrections=[
        BoundaryCitationPatch(subject_id="conclusion", field="limitations",
                              values=["No source excerpt was delivered for app/api.py."])])
    repaired = _repair_exec(turn)._apply_citation_repair(repair)
    assert repaired.conclusion.status == "inconclusive"
    assert repaired.conclusion.limitations == ["No source excerpt was delivered for app/api.py."]
    assert [item.claim_id for item in repaired.conclusion.claim_assessments] == ["document_claim_x"]


def test_repair_fixes_candidate_identity_without_touching_evidence():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryCitationPatch,
        BoundaryCitationRepair,
    )
    candidate = {"id": "dup", "criterion_id": "invented", "title": "Boundary",
        "description": "Observed.", "kind": "design_observation", "components": ["app/api.py"],
        "evidence_ids": ["ev-1"], "justification": "Observed use.", "modularity_impact": "Local.",
        "severity": "low", "confidence": 0.5, "recommendation": "Review.",
        "inferred_boundary": "No direct import.", "contradictory_dependency": "Direct import.",
        "technical_basis": "Source cited.", "document_claim_ids": ["document_claim_x"]}
    turn = _turn_with_conclusion(status="finding_candidate", candidates=[candidate])
    execution = _repair_exec(turn)
    execution._citation_error = "duplicate_candidate_or_unknown_criterion"
    repair = BoundaryCitationRepair(action="patch", corrections=[
        BoundaryCitationPatch(subject_id="dup", field="criterion_id", values=["architectural-boundaries"]),
        BoundaryCitationPatch(subject_id="dup", field="id", values=["unique-candidate"])])
    repaired = execution._apply_citation_repair(repair)
    fixed = repaired.conclusion.candidates[0]
    assert fixed.id == "unique-candidate" and fixed.criterion_id == "architectural-boundaries"
    assert fixed.evidence_ids == ["ev-1"] and fixed.document_claim_ids == ["document_claim_x"]


def test_mismatch_errors_report_contradicted_claims():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.investigation import (
        reference_errors,
    )
    candidate = {"id": "cand-1", "criterion_id": "architectural-boundaries", "title": "Boundary",
        "description": "Observed.", "kind": "design_observation", "components": ["app/api.py"],
        "evidence_ids": ["ev-1"], "justification": "Observed use.", "modularity_impact": "Local.",
        "severity": "low", "confidence": 0.5, "recommendation": "Review.",
        "inferred_boundary": "No direct import.", "contradictory_dependency": "Direct import.",
        "technical_basis": "Source cited.", "document_claim_ids": ["wrong-claim"]}
    assessment = {"claim_id": "document_claim_x", "status": "contradicted",
        "rationale": "Contradicted.", "code_evidence_ids": ["ev-1"], "scope_paths": ["app/api.py"],
        "exceptions_examined": [], "limitations": [], "assessment_origin": "investigator"}
    turn = _turn_with_conclusion(status="finding_candidate", candidates=[candidate],
                                 claim_assessments=[assessment])
    catalog = {"evidence": [], "examined_relationships": [], "planned_only_relationship_ids": [],
               "source_evidence_by_component": {}}
    errors = reference_errors(turn, "candidate_document_claim_mismatch", catalog)
    mismatch = next(item for item in errors if item["subject_id"] == "candidate:0")
    assert mismatch["contradicted_claim_ids"] == ["document_claim_x"]
    assert mismatch["candidate_document_claim_ids"] == ["wrong-claim"]


def test_documentary_traceability_chain_is_preserved(tmp_path):
    tools = small_tools(tmp_path)
    rule = claim("app.api must not depend on app.store implementations.",
                 subject="app.api", related=["app.store"])
    source = context(tools, [rule])
    menu, inventory, _ = prepare(tools, source)
    task = docs(menu)[0]
    record = inventory["_document_claims"][task.document_claim_ids[0]]
    assert record.claim.section_ids == ["s1"]
    assert record.section_paths == {"s1": "docs/rules.md"}
    assert task.document_claim_ids[0] in inventory["_document_claims"]
    assert record.portions[0].opportunity_ids == [task.id]


def test_missing_assessments_close_inconclusive_with_limitations(tmp_path):
    tools = small_tools(tmp_path)
    rule = claim("app.api must not depend on app.store implementations.",
                 subject="app.api", related=["app.store"])
    menu, _inventory, _ = prepare(tools, context(tools, [rule]))
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.document_investigation import (
        pending_assessments,
    )
    pending = pending_assessments(docs(menu)[0], [], {})
    assert pending and pending[0].status == "inconclusive" and pending[0].limitations


def test_layer_route_prohibition_inspects_the_consumer(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { prisma } from '@/lib/prisma';\nexport async function GET() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
    })
    ownership = claim("La Capa Route se encuentra en app/api/.", subject="Capa Route",
                      related=[], category="components", constraint="unspecified")
    rule = claim("Está prohibido importar @/lib/prisma en la Capa Route.",
                 subject="Capa Route", related=["@/lib/prisma"])
    menu, inventory, _ = prepare(tools, context(tools, [ownership, rule]))
    task = docs(menu)[0]
    assert task.scope[0] == "app/api/route.ts"
    strategy = {query.tool: query.arguments for query in task.investigation_strategy}
    route_id = next(f.id for f in tools.accessible_snapshot.files if f.path == "app/api/route.ts")
    assert strategy["list_relationships"]["source_id"] == route_id
    record = inventory["_document_claims"][task.document_claim_ids[0]]
    assert record.subject_paths == ["app/api/route.ts"]


def test_unresolved_subject_does_not_guess_consumers_from_incoming_edges(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { prisma } from '../../lib/prisma';\nexport async function GET() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
    })
    # No layer label: only the destination resolves. Incoming Prisma consumers
    # must not be promoted into guessed regulated origins.
    rule = claim("Está prohibido importar @/lib/prisma en la Capa Route.",
                 subject="Capa Route", related=["@/lib/prisma"])
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    assert not docs(menu)
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "unmapped"
    assert "regulated subject unresolved" in record.reason


def test_literal_next_parameter_route_does_not_match_siblings(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/roles/[id]/route.ts": "export async function GET() {}\n",
        "app/api/roles/settings/route.ts": "export async function GET() {}\n",
        "src/lib/prisma.ts": "export const prisma = {};\n",
    })
    rule = claim("Handlers in app/api/roles/[id]/route.ts must not import @/lib/prisma.",
                 subject="app/api/roles/[id]/route.ts")
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert "app/api/roles/[id]/route.ts" in record.scope_paths
    assert "app/api/roles/settings/route.ts" not in record.scope_paths


def test_eslint_config_claim_is_not_a_code_boundary_contradiction(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { prisma } from '@/lib/prisma';\nexport async function GET() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
        "eslint.config.mjs": "export default [];\n",
    })
    rule = claim("La regla ESLint no-restricted-imports prohíbe importar @/lib/prisma en app/api/**.",
                 subject="eslint.config.mjs", related=["app/api/**"])
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.boundary_family is None and record.status == "not_applicable"
    assert not docs(_menu)


def test_mixed_eslint_and_architecture_statement_keeps_the_dependency_clause(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { prisma } from '@/lib/prisma';\nexport async function GET() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
    })
    rule = claim("Los handlers no importan Prisma y ESLint no emite warnings.",
                 subject="app/api/route.ts", related=["@/lib/prisma"])
    _menu, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.boundary_family == "dependency" and record.status == "applicable"
    assert "app/api/route.ts" in record.subject_paths


def test_route_prohibition_stays_within_route_scope(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { prisma } from '@/lib/prisma';\nexport async function GET() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
        "lib/services/orders.ts": "import { prisma } from '@/lib/prisma';\nexport function orders() { return prisma; }\n",
    })
    ownership = claim("La Capa Route se encuentra en app/api/.", subject="Capa Route",
                      related=[], category="components", constraint="unspecified")
    route_rule = claim("Está prohibido importar @/lib/prisma en la Capa Route.",
                       subject="Capa Route", related=["@/lib/prisma"])
    service_rule = claim("Solo Capa Service puede importar @/lib/prisma.",
                         subject="Capa Service", related=["@/lib/prisma"], constraint="allowed")
    service_ownership = claim("La Capa Service se ubica en lib/services/.", subject="Capa Service",
                              related=[], category="responsibilities", constraint="unspecified")
    menu, inventory, _ = prepare(tools, context(tools, [ownership, route_rule, service_ownership, service_rule]))
    route_task = next(task for task in docs(menu)
                      if inventory["_document_claims"][task.document_claim_ids[0]].subject_paths
                      == ["app/api/route.ts"])
    assert "lib/services/orders.ts" not in route_task.scope
    service_record = inventory["_document_claims"][next(
        task.document_claim_ids[0] for task in docs(menu)
        if inventory["_document_claims"][task.document_claim_ids[0]].claim.constraint == "allowed")]
    assert service_record.subject_paths == ["lib/services/orders.ts"]
    assert "app/api/route.ts" not in service_record.scope_paths


def test_framework_use_restriction_on_service_layer_is_dependency(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/service.ts": "export function run() {}\n",
        "app/api/route.ts": "export async function GET() {}\n",
    })
    ownership = claim("La Capa Service se encuentra en app/service.", subject="Capa Service",
                      related=[], category="components", constraint="unspecified")
    rule = claim("Está prohibido utilizar NextRequest/NextResponse en la Capa Service.",
                 subject="Capa Service", related=["app/api/route.ts"])
    menu, inventory, _ = prepare(tools, context(tools, [ownership, rule]))
    record = inventory["_document_claims"][menu and docs(menu)[0].document_claim_ids[0]]
    assert record.boundary_family == "dependency" and record.status == "applicable"
    assert "app/service.ts" in record.subject_paths


def test_planned_edges_are_navigation_until_tools_verify_them(tmp_path):
    tools = small_tools(tmp_path)
    rule = claim("app.api must not depend on app.store implementations.",
                 subject="app.api", related=["app.store"])
    menu, _inventory, _ = prepare(tools, context(tools, [rule]))
    task = docs(menu)[0]
    assert task.structural_signal.relationships
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.investigation import (
        reference_catalog,
        relationship_query,
    )
    first = task.structural_signal.relationships[0]
    query = relationship_query(tools.accessible_snapshot, first)
    assert query["arguments"]["source_id"] == first.source_id
    assert query["arguments"]["target_id"] == first.target_id
    assert query["arguments"]["kind"] == first.kind
    empty = {"source_evidence_by_component": {}, "examined_relationships": [],
             "planned_only_relationship_ids": [], "verification_queries": {}, "evidence": []}
    catalog = reference_catalog(tools.accessible_snapshot, [], {}, task)
    assert first.id in catalog["planned_only_relationship_ids"]
    assert not empty["examined_relationships"]


def test_repair_by_position_preserves_duplicated_candidates():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryCitationPatch,
        BoundaryCitationRepair,
    )
    candidate = {"id": "dup", "criterion_id": "invented", "title": "Boundary",
        "description": "Observed.", "kind": "design_observation", "components": ["app/api.py"],
        "evidence_ids": ["ev-1"], "justification": "Observed use.", "modularity_impact": "Local.",
        "severity": "low", "confidence": 0.5, "recommendation": "Review.",
        "inferred_boundary": "No direct import.", "contradictory_dependency": "Direct import.",
        "technical_basis": "Source cited.", "document_claim_ids": []}
    turn = _turn_with_conclusion(status="finding_candidate",
                                 candidates=[dict(candidate), dict(candidate)])
    execution = _repair_exec(turn)
    repair = BoundaryCitationRepair(action="patch", corrections=[
        BoundaryCitationPatch(subject_id="candidate:1", field="criterion_id", values=["architectural-boundaries"]),
        BoundaryCitationPatch(subject_id="candidate:1", field="id", values=["unique-candidate"])])
    repaired = execution._apply_citation_repair(repair)
    first, second = repaired.conclusion.candidates
    assert first.id == "dup" and first.criterion_id == "invented"
    assert second.id == "unique-candidate" and second.criterion_id == "architectural-boundaries"
    assert second.evidence_ids == ["ev-1"]


def test_mismatch_repair_preserves_contradiction_evidence():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryCitationPatch,
        BoundaryCitationRepair,
    )
    candidate = {"id": "cand-1", "criterion_id": "architectural-boundaries", "title": "Boundary",
        "description": "Observed.", "kind": "design_observation", "components": ["app/api.py"],
        "evidence_ids": ["ev-1"], "justification": "Observed use.", "modularity_impact": "Local.",
        "severity": "low", "confidence": 0.5, "recommendation": "Review.",
        "inferred_boundary": "No direct import.", "contradictory_dependency": "Direct import.",
        "technical_basis": "Source cited.", "document_claim_ids": ["wrong-claim"]}
    assessment = {"claim_id": "document_claim_x", "status": "contradicted",
        "rationale": "Contradicted.", "code_evidence_ids": ["ev-1", "ev-2"], "scope_paths": ["app/api.py"],
        "exceptions_examined": [], "limitations": [], "assessment_origin": "investigator"}
    turn = _turn_with_conclusion(status="finding_candidate", candidates=[candidate],
                                 claim_assessments=[assessment])
    repair = BoundaryCitationRepair(action="patch", corrections=[
        BoundaryCitationPatch(subject_id="candidate:0", field="document_claim_ids",
                              values=["document_claim_x"])])
    repaired = _repair_exec(turn)._apply_citation_repair(repair)
    assert repaired.conclusion.candidates[0].document_claim_ids == ["document_claim_x"]
    assert repaired.conclusion.candidates[0].evidence_ids == ["ev-1"]
    assert [item.claim_id for item in repaired.conclusion.claim_assessments] == ["document_claim_x"]


def test_citation_gaps_diagnose_multiple_errors_jointly():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.investigation import (
        citation_gaps,
    )
    turn = _turn_with_conclusion(components=["app/api.py"], evidence_ids=["unknown-ev"],
                                 relationship_ids=["unexamined-rel"])
    catalog = {"evidence": [], "examined_relationships": [], "planned_only_relationship_ids": [],
               "source_evidence_by_component": {}}
    gaps = citation_gaps(turn, catalog)
    fields = {(item["field"], item["missing"]) for item in gaps}
    assert ("evidence_ids", "unknown-ev") in fields
    assert ("components", "app/api.py") in fields
    assert ("relationship_ids", "unexamined-rel") in fields


def test_citation_gaps_identify_dependency_endpoints_without_source():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.investigation import (
        citation_gaps,
    )
    turn = _turn_with_conclusion(components=["app/api.py", "lib/prisma.ts"],
                                 relationship_ids=["rel-1"], evidence_ids=["ev-a", "ev-b"])
    catalog = {"evidence": [
            {"id": "ev-a", "path": "app/api.py", "kind": "source", "file_id": "file-a",
             "start_line": 1, "end_line": 2, "symbol_ids": []},
            {"id": "ev-b", "path": "lib/prisma.ts", "kind": "metadata", "file_id": "file-b",
             "start_line": 1, "end_line": 1, "symbol_ids": []}],
        "examined_relationships": [{"id": "rel-1", "kind": "import",
            "source_path": "app/api.py", "target_path": "lib/prisma.ts",
            "source_evidence_ids": {"app/api.py": ["ev-a"]},
            "missing_source_paths": ["lib/prisma.ts"]}],
        "planned_only_relationship_ids": [], "verification_queries": {},
        "source_evidence_by_component": {"app/api.py": ["ev-a"]}}
    gaps = citation_gaps(turn, catalog)
    assert {"subject": "conclusion", "field": "dependency_endpoints",
            "missing": "lib/prisma.ts", "relationship_id": "rel-1"} in gaps


def test_finding_keeps_documentary_trace_separate_from_code_evidence():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryFinding,
    )
    finding = BoundaryFinding.model_validate({
        "id": "candidate-1", "title": "Boundary contradiction", "description": "Observed import.",
        "criterion_id": "architectural-boundaries", "kind": "design_observation",
        "components": ["app/api.py"], "evidence_ids": ["ev-technical"],
        "justification": "Source evidence.", "modularity_impact": "Local boundary.",
        "severity": "low", "confidence": 0.8, "recommendation": "Review the dependency.",
        "criterion": {"id": "architectural-boundaries", "origin": "design_principle",
            "description": "Boundary check.", "provenance": "Local test."},
        "evidence": [], "document_claim_ids": ["document_claim_1"],
        "investigation_ids": ["investigation-1"],
        "documentary_claim_refs": [{"claim_id": "document_claim_1", "section_ids": ["s1"],
            "section_paths": {"s1": "docs/rules.md"}, "document_paths": ["docs/rules.md"]}],
    })
    assert finding.document_claim_ids == ["document_claim_1"]
    assert finding.investigation_ids == ["investigation-1"]
    assert finding.documentary_claim_refs[0].section_paths == {"s1": "docs/rules.md"}
    assert "document_claim_1" not in finding.evidence_ids


def test_inconclusive_repair_preserves_valid_assessments():
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryCitationRepair,
    )
    assessment = {"claim_id": "document_claim_x", "status": "contradicted",
        "rationale": "Contradicted locally.", "code_evidence_ids": ["ev-1"], "scope_paths": ["app/api.py"],
        "exceptions_examined": [], "limitations": [], "assessment_origin": "investigator"}
    turn = _turn_with_conclusion(status="finding_candidate", evidence_ids=["ev-1"],
                                 claim_assessments=[assessment],
                                 limitations=["Local scope only."])
    repair = BoundaryCitationRepair(action="inconclusive",
        limitation="Citation requirements could not be satisfied locally.")
    repaired = _repair_exec(turn)._apply_citation_repair(repair)
    assert repaired.conclusion.status == "inconclusive"
    assert [item.claim_id for item in repaired.conclusion.claim_assessments] == ["document_claim_x"]
    assert "Citation requirements could not be satisfied locally." in repaired.conclusion.limitations


def test_cached_evidence_recovery_is_progress(tmp_path):
    import asyncio
    from types import SimpleNamespace

    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
        BoundaryConfig,
    )
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
        BoundaryExecution,
    )
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryToolQuery,
    )

    tools = small_tools(tmp_path)
    config = BoundaryConfig(provider_request_interval_seconds=0, max_output_tokens=1000)

    class StubModel:
        def bind_tools(self, tools):
            return self

    execution = BoundaryExecution(StubModel(), config, tools, AuditRequest())
    menu, _inventory, _ = prepare(tools, None)
    task = next((item for item in menu if item.structural_signal.kind == "documented_boundary"), menu[0])
    state = execution.initial_state()
    state.update(plan=SimpleNamespace(investigations=[task]), current_investigation=0)
    state["task_budget"] = execution._new_task_budget(state)
    query = BoundaryToolQuery(tool="get_source_excerpt",
        arguments={"path": task.scope[0], "start_line": 1, "end_line": 3},
        reason="Inspect the planned boundary endpoint.")
    state["pending_queries"] = [query]
    state.update(asyncio.run(execution.execute_investigation_tools(state)))
    assert state["active_query_keys"] and state["no_progress_turns"] == 0
    calls = tools.budget_usage.tool_calls
    # Same query reactivated from cache after omission from the context.
    state["active_query_keys"] = []
    state["pending_queries"] = [query]
    state.update(asyncio.run(execution.execute_investigation_tools(state)))
    assert state["no_progress_turns"] == 0
    assert tools.budget_usage.tool_calls == calls
    # A truly repeated turn with the view still active is not progress.
    state["pending_queries"] = [query]
    state.update(asyncio.run(execution.execute_investigation_tools(state)))
    assert state["no_progress_turns"] == 1

"""Local regression checks for documentary resolution and classification.

These fixtures deliberately remain inside this agent package; they do not
depend on state or findings from any shared agent.
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
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.document_mapping import (
    DocumentCodeResolver,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.documentation import (
    _domain,
    prepare_documentation,
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
        budget=ExecutionBudget(max_input_tokens_per_call=50_000),
    )), workspace_root=tmp_path)


def claim(statement, subject="app/api", related=None, **updates):
    return KnowledgeClaim.model_validate({
        "category": "constraints",
        "subject": subject,
        "statement": statement,
        "related_subjects": related or [],
        "certainty": "explicit",
        "section_ids": ["s1"],
        "reasoning": "Obligación arquitectónica adoptada.",
        "constraint": "prohibited",
        "evidence": [{
            "section_id": "s1", "start_line": 1, "end_line": 1,
            "quote": statement + "\n",
        }],
        **updates,
    })


def definition(name, statement, **updates):
    return claim(
        statement,
        subject=name,
        related=[],
        category="responsibilities",
        constraint="unspecified",
        reasoning="Definición documental de capa.",
        **updates,
    )


def context(tools, claims):
    snapshot = tools.accessible_snapshot
    index = IndexReference(
        index_id="index",
        repository_id=identifier(str(__import__("pathlib").Path(snapshot.repository.root_path).resolve())),
        commit=snapshot.repository.commit,
    )
    return ArchitectureContextResult.model_validate({
        "document_index": index,
        "knowledge": claims,
        "knowledge_issues": [],
        "covered_categories": [],
        "pending_categories": list(get_args(RetrievalCategory)),
        "evaluated_categories": list(get_args(RetrievalCategory)),
        "coverage_assessment_status": "completed",
        "consulted_documents": [DocumentRecord(
            **index.model_dump(), path="docs/rules.md", content_hash="hash", line_count=10)],
        "section_paths": {"s1": "docs/rules.md"},
        "validation_errors": [],
        "execution_status": "partial",
        "finalization_reason": "incomplete_coverage",
    })


def prepare(tools, claims):
    snapshot = tools.accessible_snapshot
    files = {file.id: file for file in snapshot.files}
    projects = {key: file.project_id for key, file in files.items()}
    return prepare_documentation(
        snapshot,
        AuditRequest(documented_architecture=context(tools, claims)),
        files,
        set(files),
        projects,
        check=lambda: None,
    )


def docs(tasks):
    return tasks


def test_narrative_words_do_not_resolve_bare_symbols(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "",
        "app/permissions.py": "class PermissionsProvider:\n    def can(self):\n        return True\n    def queries(self):\n        return []\n",
    })
    snapshot = tools.accessible_snapshot
    resolver = DocumentCodeResolver(
        {file.id: file for file in snapshot.files},
        snapshot.symbols,
        lambda: None,
    )
    result = resolver.resolve("Users can query orders; queries are common in this narration.")
    assert result["ids"] == set()
    assert "can" not in result["matches"]
    assert "queries" not in result["matches"]


def test_explicit_symbol_reference_still_resolves(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/__init__.py": "",
        "app/permissions.py": "class PermissionsProvider:\n    def can(self):\n        return True\n",
    })
    snapshot = tools.accessible_snapshot
    resolver = DocumentCodeResolver(
        {file.id: file for file in snapshot.files},
        snapshot.symbols,
        lambda: None,
    )
    result = resolver.resolve("Use `PermissionsProvider.can` explicitly.")
    assert result["ids"] == {symbol.file_id for symbol in snapshot.symbols
                             if symbol.name == "can" and symbol.file_id
                             and snapshot.files[next(i for i, f in enumerate(snapshot.files)
                                                       if f.id == symbol.file_id)].path == "app/permissions.py"}


def test_monetary_importes_is_not_an_import_obligation():
    money_claim = claim(
        "Los importes monetarios deben mostrarse en el reporte.",
        subject="Reporte",
        related=[],
        constraint="unspecified",
    )
    family, _reason = _domain(money_claim)
    assert family is None


def test_layer_definitions_resolve_route_and_service(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "export async function GET() {}\n",
        "app/api/nested/route.ts": "export async function POST() {}\n",
        "lib/services/orders.ts": "export function orders() {}\n",
        "src/modules/billing/services.ts": "export function billing() {}\n",
        "lib/prisma.ts": "export const prisma = {};\n",
    })
    route_definition = definition("Capa Route", "CAPA ROUTE (app/api/**/route.ts)")
    service_definition = definition(
        "Capa Service",
        "CAPA SERVICE (lib/services/** o src/modules/**/services)",
    )
    route_rule = claim(
        "Está prohibido importar @/lib/prisma en la Capa Route.",
        subject="Capa Route",
        related=["@/lib/prisma"],
    )
    service_rule = claim(
        "Capa Service no debe importar NextRequest desde app/api/**/route.ts.",
        subject="Capa Service",
        related=["app/api/**/route.ts"],
    )
    tasks, records, _diagnostics, _warnings = prepare(
        tools,
        [route_definition, service_definition, route_rule, service_rule],
    )
    record_by_claim = {record.claim.statement: record for record in records.values()}
    route_record = record_by_claim[route_rule.statement]
    service_record = record_by_claim[service_rule.statement]
    assert route_record.status == "applicable"
    assert route_record.subject_paths == ["app/api/nested/route.ts", "app/api/route.ts"]
    assert "lib/services/orders.ts" not in route_record.scope_paths
    assert service_record.status == "applicable"
    assert service_record.subject_paths == [
        "lib/services/orders.ts", "src/modules/billing/services.ts"
    ]
    assert "app/api/nested/route.ts" in service_record.scope_paths
    assert all("lib/services/orders.ts" not in task.scope or "src/modules/billing/services.ts" in task.scope
               for task in tasks)


def test_route_prohibition_creates_no_service_scope_tasks(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/api/route.ts": "import { prisma } from '@/lib/prisma';\nexport async function GET() { return prisma; }\n",
        "lib/prisma.ts": "export const prisma = {};\n",
        "lib/services/orders.ts": "import { prisma } from '@/lib/prisma';\nexport function orders() { return prisma; }\n",
    })
    ownership = claim(
        "La Capa Route se encuentra en app/api/.",
        subject="Capa Route", related=[], category="components", constraint="unspecified",
    )
    rule = claim(
        "Está prohibido importar @/lib/prisma en la Capa Route.",
        subject="Capa Route", related=["@/lib/prisma"],
    )
    tasks, records, _diagnostics, _warnings = prepare(tools, [ownership, rule])
    record = next(record for record in records.values() if record.claim.statement == rule.statement)
    assert record.status == "applicable"
    assert "lib/services/orders.ts" not in record.scope_paths
    assert all("lib/services/orders.ts" not in task.scope for task in docs(tasks))


def test_brace_pattern_is_exact_and_id_is_literal(tmp_path):
    contents = {}
    for name in ("tables", "settings", "payment-methods", "roles", "purchases"):
        contents[f"app/api/{name}/route.ts"] = "export async function GET() {}\n"
    contents["src/lib/prisma.ts"] = "export const prisma = {};\n"
    tools = indexed_tools(tmp_path, contents)
    limited = claim(
        "app/api/{tables,settings,payment-methods,roles} must not import @/lib/prisma.",
        subject="app/api/{tables,settings,payment-methods,roles}",
        related=["@/lib/prisma"],
    )
    _tasks, records, _diagnostics, _warnings = prepare(tools, [limited])
    record = next(iter(records.values()))
    assert "app/api/purchases/route.ts" not in record.scope_paths
    assert {"app/api/tables/route.ts", "app/api/settings/route.ts",
            "app/api/payment-methods/route.ts", "app/api/roles/route.ts"} <= set(record.scope_paths)

    id_tools = indexed_tools(tmp_path, {
        "app/api/roles/[id]/route.ts": "export async function GET() {}\n",
        "app/api/roles/settings/route.ts": "export async function GET() {}\n",
        "src/lib/prisma.ts": "export const prisma = {};\n",
    })
    id_rule = claim(
        "Handlers in app/api/roles/[id]/route.ts must not import @/lib/prisma.",
        subject="app/api/roles/[id]/route.ts",
        related=["@/lib/prisma"],
    )
    _tasks, records, _diagnostics, _warnings = prepare(id_tools, [id_rule])
    record = next(iter(records.values()))
    assert "app/api/roles/[id]/route.ts" in record.scope_paths
    assert "app/api/roles/settings/route.ts" not in record.scope_paths


def test_patterns_stay_in_their_documented_subproject(tmp_path):
    tools = indexed_tools(tmp_path, {
        "west/app/api/route.ts": "export async function GET() {}\n",
        "east/app/api/route.ts": "export async function GET() {}\n",
        "src/lib/prisma.ts": "export const prisma = {};\n",
    })
    rule = claim(
        "west/app/api/**/route.ts must not import @/lib/prisma.",
        subject="west/app/api/**",
        related=["@/lib/prisma"],
    )
    _tasks, records, _diagnostics, _warnings = prepare(tools, [rule])
    record = next(iter(records.values()))
    assert "west/app/api/route.ts" in record.scope_paths
    assert "east/app/api/route.ts" not in record.scope_paths


def test_ambiguous_suffixes_remain_ambiguous(tmp_path):
    tools = indexed_tools(tmp_path, {
        "src/shoplab/bootstrap.py": "def build(): pass\n",
        "legacy/shoplab/bootstrap.py": "def build(): pass\n",
    })
    rule = claim(
        "Bindings must be assembled in shoplab/bootstrap.py.",
        subject="Composition boundary", related=[], constraint="required",
    )
    _tasks, records, _diagnostics, _warnings = prepare(tools, [rule])
    record = next(iter(records.values()))
    assert record.mapping_basis == "ambiguous" and record.status == "unmapped"


def test_small_project_still_maps_the_architectural_rule(tmp_path):
    tools = indexed_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "from .store import Store\nclass Api:\n    pass\n",
        "app/store.py": "from .api import Api\nclass Store:\n    pass\n",
    })
    rule = claim(
        "app.api must not depend on app.store implementations.",
        subject="app.api", related=["app.store"],
    )
    tasks, records, _diagnostics, _warnings = prepare(tools, [rule])
    record = next(iter(records.values()))
    assert tasks and record.status == "applicable"


def test_dependency_applicability_requires_the_regulated_relation():
    from types import SimpleNamespace

    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.document_mapping import (
        relation_applies,
    )

    route_claim = claim(
        "Está prohibido importar @/lib/prisma en la Capa Route.",
        subject="Capa Route", related=["@/lib/prisma"],
    )
    record = SimpleNamespace(
        claim=route_claim,
        boundary_family="dependency",
        excluded_paths=[],
        scope_paths=[
            "app/api/customers/route.ts", "app/charts/DashboardCharts.tsx",
            "app/charts/dashboard.service.ts", "lib/prisma.ts", "lib/services/purchases.ts",
        ],
        subject_paths=["app/api/customers/route.ts"],
        owner_paths={
            "Capa Route": ["app/api/customers/route.ts"],
            "@/lib/prisma": ["lib/prisma.ts"],
            "dashboard.service.ts": ["app/charts/dashboard.service.ts"],
        },
    )
    assert relation_applies(record, "app/api/customers/route.ts", "lib/prisma.ts")
    assert not relation_applies(record, "app/charts/DashboardCharts.tsx", "app/charts/dashboard.service.ts")
    assert not relation_applies(record, "lib/services/purchases.ts", "lib/prisma.ts")
    assert not relation_applies(record, "lib/prisma.ts", "app/api/customers/route.ts")


def test_favorable_documentary_claims_cannot_ground_a_finding_candidate():
    from types import SimpleNamespace

    import pytest

    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
        BoundaryExecution,
    )
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryInvestigationResult,
    )

    task = SimpleNamespace(document_claim_ids=["c1"], id="task-1")
    state = SimpleNamespace(
        plan=SimpleNamespace(investigations=[task]),
        current_investigation=0,
    )
    assessment = {
        "claim_id": "c1", "status": "supported",
        "rationale": "Compatible managed import.", "code_evidence_ids": ["ev-supported"],
        "scope_paths": ["lib/services/employee-helper.ts"],
        "exceptions_examined": [], "limitations": [], "assessment_origin": "investigator",
    }
    candidate = {
        "id": "candidate-favorable", "title": "Favorable service dependency",
        "description": "The helper imports Prisma.", "criterion_id": "architectural-boundaries",
        "kind": "design_observation", "components": ["lib/services/employee-helper.ts"],
        "evidence_ids": ["ev-supported"], "justification": "The dependency is authorized.",
        "modularity_impact": "No contradiction.", "severity": "low", "confidence": 0.8,
        "recommendation": "None.", "inferred_boundary": "Prisma is managed by helper.",
        "contradictory_dependency": "Employee helper imports Prisma.",
        "technical_basis": "Source evidence.",
    }
    result = BoundaryInvestigationResult(
        investigation_id="task-1", status="finding_candidate", summary="Candidate",
        justification="Contradiction.",
        components=["lib/services/employee-helper.ts"], evidence_ids=["ev-supported"],
        claim_assessments=[assessment], candidates=[candidate],
    )
    execution = BoundaryExecution.__new__(BoundaryExecution)
    execution.tools = SimpleNamespace(accessible_snapshot=SimpleNamespace(symbols=[]))
    execution.evidence_issues = lambda evidence_ids, references: ([], [])
    execution._documentary_context = lambda state_: {
        "claims": {"c1": {"status": "applicable", "certainty": "explicit",
                          "execution_status": "partial", "knowledge_issues": [],
                          "validation_errors": []}},
        "unavailable_claims": {},
    }
    source = SimpleNamespace(
        id="ev-supported", kind="source", path="lib/services/employee-helper.ts",
        file_id="file-helper", start_line=1, end_line=3, symbol_ids=[],
    )
    with pytest.raises(ValueError, match="candidate_document_claim_mismatch"):
        execution._validate_claim_assessments(
            result, task, state, {"ev-supported": source})

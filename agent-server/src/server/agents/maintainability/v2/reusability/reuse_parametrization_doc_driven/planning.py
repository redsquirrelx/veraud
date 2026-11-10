"""Documentary normalization and semantic source-free parametrization planning.

The planner sends compact documentary knowledge to the LLM in bounded batches;
the model discovers variation points and the host grounds, validates and
deduplicates its proposals. Reading source belongs to investigate.
"""

import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
    KnowledgeEvidence,
)
from server.contracts.audit import Hypothesis
from server.services.document_indexing import IndexReference
from server.services.repository_analysis.context import create_identifier
from server.services.repository_analysis.testing import is_test_file

from .schemas import (
    ParametrizationCandidate,
    ParametrizationConsolidationResponse,
    ParametrizationDocumentClaim,
    ParametrizationPlan,
)

MAX_REFERENCE_SYMBOLS = 90
MAX_REFERENCE_FILES = 60
MAX_PROMPT_JSON_CHARS = 80_000


def _as_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{context} must be an ArchitectureContextResult or a mapping, not {type(value).__name__}.")


def normalize_knowledge(context: ArchitectureContextResult | Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if context is None:
        return []
    data = _as_mapping(context, context="context")
    knowledge = list(data.get("knowledge") or [])
    if not knowledge:
        return []

    document_index_raw = data.get("document_index")
    if document_index_raw is None:
        raise ValueError("documented_architecture.document_index is required to normalize documentary knowledge.")
    index = _as_mapping(document_index_raw, context="context.document_index")
    index_id = index.get("index_id")
    if not isinstance(index_id, str) or not index_id.strip():
        raise ValueError("documented_architecture.document_index.index_id must be a non-empty string.")

    document_index = None
    if isinstance(document_index_raw, BaseModel):
        document_index_raw = document_index_raw.model_dump(mode="json")
    if isinstance(document_index_raw, Mapping):
        try:
            document_index = IndexReference.model_validate({field: document_index_raw.get(field)
                for field in ("index_id", "repository_id", "commit")})
        except Exception:  # noqa: BLE001 - malformed index reference is degraded honestly
            document_index = None

    section_paths = data.get("section_paths")
    if not isinstance(section_paths, Mapping):
        section_paths = {}

    claims: list[dict[str, Any]] = []
    for index, entry in enumerate(knowledge):
        claim = KnowledgeClaim.model_validate(entry)
        evidence = [KnowledgeEvidence.model_validate(item).model_dump(mode="json") for item in claim.evidence]
        claims.append({
            "id": f"{index_id}:{index}",
            "category": claim.category,
            "subject": claim.subject,
            "statement": claim.statement,
            "related_subjects": list(claim.related_subjects),
            "certainty": claim.certainty,
            "constraint": claim.constraint,
            "section_ids": list(claim.section_ids),
            "evidence": evidence,
            "document_index": document_index.model_dump(mode="json") if document_index else None,
            "section_paths": {section_id: section_paths[section_id] for section_id in claim.section_ids
                if section_id in section_paths},
        })
    return claims


def _words(text: str) -> list[str]:
    split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return [token.casefold() for token in re.findall(r"[A-Za-z0-9]+", split)]


def _token_set(text: str) -> set[str]:
    return {token for token in _words(text) if len(token) >= 3 and token not in {
        "the", "and", "that", "this", "with", "from", "into", "responsibility", "component", "module",
    }}


def _normalized_reference(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())



def _split_words(text: str) -> list[str]:
    return _words(text)


def _path_relevance(claim_tokens: list[set[str]], path: str, module: str | None) -> int:
    path_tokens = _token_set(f"{path} {module or ''}")
    return sum(len(tokens & path_tokens) for tokens in claim_tokens)


def _symbol_relevance(claim_tokens: list[set[str]], symbol) -> int:
    symbol_tokens = _token_set(f"{symbol.name} {symbol.qualified_name}")
    return sum(min(3, len(tokens & symbol_tokens)) for tokens in claim_tokens)


def nonproduction_path(path: str) -> bool:
    lowered = path.casefold().replace("\\", "/")
    parts = PurePosixPath(lowered).parts
    return (is_test_file(lowered) or PurePosixPath(lowered).name == "conftest.py"
        or any(re.search(r"(?:^|[._-])(?:tests?|specs?|fixtures?|mocks?)(?:[._-]|$)", part)
            for part in parts))


def _matches_selector(value: str, file, symbols) -> bool:
    return (value in (file.id, file.path, file.module_name)
        or file.path.startswith(value.rstrip("/") + "/")
        or (value in symbols and symbols[value].file_id == file.id))


def _select_reference_entities(all_files, symbols_by_file, claims) -> list[dict]:
    claim_tokens: list[set[str]] = [
        _token_set(" ".join(str(claim.get(field, "")) for field in ("subject", "statement", "constraint"))
            + " " + " ".join(str(value) for value in claim.get("related_subjects", ())))
        for claim in claims
    ]
    claim_text_norm = [
        _normalized_reference(" ".join((item.get("subject", ""), *item.get("related_subjects", ()), item.get("statement", ""))))
        for item in claims
    ]
    if not claim_tokens:
        return []

    scored_files = [(file, _path_relevance(claim_tokens, file.path, file.module_name))
        for file in all_files.values()]
    scored_symbols = []
    for file in all_files.values():
        for symbol in symbols_by_file[file.id]:
            relevance = _symbol_relevance(claim_tokens, symbol)
            symbol_key = _normalized_reference(symbol.name)
            if symbol_key and len(symbol_key) >= 4:
                direct_hits = sum(1 for claim in claims
                    if symbol_key in _normalized_reference(" ".join((claim.get("subject", ""),
                        *claim.get("related_subjects", ())))))
                relevance += 1000 * direct_hits
                relevance += 50 * sum(1 for normalized in claim_text_norm if symbol_key in normalized)
            if relevance > 0:
                scored_symbols.append((symbol, relevance))
    scored_symbols.sort(key=lambda item: (-item[1], item[0].id))
    scored_files.sort(key=lambda item: (-item[1], item[0].path))
    selected = (
        [(symbol.id, symbol, score, "symbol") for symbol, score in scored_symbols[:MAX_REFERENCE_SYMBOLS]]
        + [(file.id, file, score, "file") for file, score in scored_files[:MAX_REFERENCE_FILES] if score > 0]
    )

    explicit_paths = {claim[field] for claim in claims
        for field in ("statement", "subject")
        for file in all_files.values()
        for path in ([file.path] + ([file.module_name] if file.module_name else []))
        if path and path.casefold() in str(claim[field]).casefold()}
    explicit_ids = {file.id for file in all_files.values() if file.path in explicit_paths}
    selected_ids = {item[0] for item in selected}
    for file in all_files.values():
        if file.id in explicit_ids - selected_ids:
            selected.append((file.id, file, 50, "file"))
    selected.sort(key=lambda item: (-item[2], item[3], item[0]))
    return [
        {
            "kind": kind,
            "path": item.path if kind == "file" else all_files[item.file_id].path,
            "file_id": item.id if kind == "file" else item.file_id,
            "module_name": item.module_name if kind == "file" else all_files[item.file_id].module_name,
            "symbol_id": item.id if kind == "symbol" else None,
            "symbol_name": item.name if kind == "symbol" else None,
            "symbol_kind": item.kind if kind == "symbol" else None,
        }
        for _entity_id, item, _score, kind in selected
    ]


def _consumer_map(snapshot, files) -> dict[str, list[str]]:
    owners = {**{file_id: file_id for file_id in files},
        **{symbol.id: symbol.file_id for symbol in snapshot.symbols if symbol.file_id in files}}
    consumers_by_file = defaultdict(set)
    for relation in snapshot.relationships:
        if relation.resolution != "internal":
            continue
        source, target = owners.get(relation.source_id), owners.get(relation.target_id)
        if source in files and target in files and source != target:
            consumers_by_file[target].add(files[source].path)
    return {file.path: sorted(consumers_by_file.get(file.id, ())) for file in files.values()}


def _brief_evidence(evidence):
    brief = []
    for item in evidence:
        quote = re.sub(r"\s+", " ", str(item.get("quote", ""))).strip()
        if len(quote) > 80:
            quote = quote[:77].rstrip() + "..."
        brief.append({
            "quote": quote,
        })
        if len(brief) == 1:
            break
    return brief


def _claim_llm_record(index: int, claim: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": f"claim-{index}",
        "category": claim["category"],
        "subject": claim["subject"],
        "statement": claim["statement"],
        "related_subjects": claim["related_subjects"],
        "constraint": claim["constraint"] if claim["constraint"] != "unspecified" else None,
        "evidence": _brief_evidence(claim["evidence"]),
    }


def _plan_batches(planning: Mapping[str, Any], request, batch_limit: int) -> list[list[dict[str, Any]]]:
    reference_json = _compact_code_references(planning["code_references"])
    overhead = len(json.dumps({
        "budget": {"max_investigations": planning["max_investigations"]},
        "objective": request.objective,
        "constraints": request.constraints,
        "evidence": reference_json,
    }, ensure_ascii=False))
    budget = max(8_000, batch_limit)
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = overhead
    for index, claim in enumerate(planning["claims"]):
        record = _claim_llm_record(index, claim)
        record_chars = len(json.dumps(record, ensure_ascii=False)) + 4
        if current and size + record_chars > budget:
            batches.append(current)
            current = []
            size = overhead
        current.append(record)
        size += record_chars
    if current:
        batches.append(current)
    return batches


def _compact_code_references(references: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for reference in references:
        group = grouped.setdefault(reference["path"], {"path": reference["path"], "symbols": []})
        if reference["kind"] == "symbol":
            group["symbols"].append({"name": reference["symbol_name"], "kind": reference["symbol_kind"]})
    order = {item["path"]: index for index, item in enumerate(references)}
    result = list(grouped.values())
    for item in result:
        if not item["symbols"]:
            item.pop("symbols")
    result.sort(key=lambda item: order.get(item["path"], len(order)))
    return result


def _plan_context(planning: Mapping[str, Any], request, prior_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "objective": request.objective,
        "constraints": request.constraints,
        "criteria": [item.model_dump() for item in request.criteria],
        "targets": request.targets,
        "budget": {"max_investigations": planning["max_investigations"]},
        "prior_accepted_candidates": prior_candidates or [],
        "code_references": _compact_code_references(planning["code_references"]),
        "limitations": planning["limitations"],
    }


def _claim_batch_context(planning: Mapping[str, Any], request, batch: list[dict], batch_index: int,
                         batch_count: int, prior_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    context = _plan_context(planning, request, prior_candidates)
    context["claims"] = batch
    context["batch"] = {"index": batch_index + 1, "count": batch_count}
    return context


def build_parametrization_planning(snapshot, request, *, check, max_investigations: int, batch_limit: int = 55_000) -> dict[str, Any]:
    check()
    all_files = {file.id: file for file in snapshot.files}
    all_symbols = {symbol.id: symbol for symbol in snapshot.symbols}
    try:
        test_paths = {path for testing in snapshot.testing for path in testing.file_paths}
    except AttributeError:
        test_paths = set()
    selectors = [value.replace("\\", "/").rstrip("/") or "." for value in (request.targets or [])]
    files = {key: file for key, file in all_files.items()
        if not (file.path in test_paths or nonproduction_path(file.path))
        or any(_matches_selector(value, file, all_symbols) for value in selectors)}
    symbols_by_file = defaultdict(list)
    for symbol in all_symbols.values():
        if symbol.file_id in files:
            symbols_by_file[symbol.file_id].append(symbol)

    limitations = [
        "Documentation is orientation, not proof of an implementation defect.",
        "Planning is source-free; reading code and confirming behavior belongs to investigate.",
    ]
    if getattr(request, "documented_architecture", None) is None:
        limitations.append("No documented architecture supplied; no variation is inferred.")
        claims = []
    else:
        try:
            claims = normalize_knowledge(request.documented_architecture)
        except (TypeError, ValueError) as error:
            claims = []
            limitations.append(f"Documentary normalization failed: {error}")

    references = _select_reference_entities(files, symbols_by_file, claims) if claims else []
    consumers_by_path = _consumer_map(snapshot, files)
    planning = {
        "snapshot_hash": snapshot.repository.snapshot_hash,
        "claims": claims,
        "code_references": references,
        "consumers_by_path": consumers_by_path,
        "symbols_by_file": symbols_by_file,
        "files": files,
        "max_investigations": max(1, min(20, max_investigations)),
        "limitations": list(dict.fromkeys(limitations)),
        "objective": request.objective,
    }
    planning["batches"] = _plan_batches(planning, request, batch_limit)
    return planning


def _valid_symbol(symbols, name: str | None):
    if not name:
        return None
    for symbol in symbols:
        if name.casefold() in {symbol.name.casefold(), symbol.qualified_name.casefold()}:
            return symbol
    return False


def _score_proposal(proposal, claim_count: int, consumers: int, symbol_present: bool) -> int:
    basis = 4 if proposal.variation_basis == "explicit" else 1
    evidence_quality = min(2, len(proposal.evidence_needed))
    mechanism_quality = 1 if len(_split_words(proposal.variation_mechanism)) >= 2 else 0
    return basis + min(3, claim_count) + min(2, consumers) + evidence_quality + mechanism_quality + (1 if symbol_present else 0)


def _structural_provisional(planning: Mapping[str, Any], responses) -> tuple[list[dict], list[str], int]:
    claims_by_local_id = {f"claim-{index}": item for index, item in enumerate(planning["claims"])}
    claims_by_id = {local_id: item["id"] for local_id, item in claims_by_local_id.items()}
    allowed_paths = {reference["path"] for reference in planning["code_references"]}
    path_to_file = {file.path: file for file in planning["files"].values()}
    provisional: list[dict] = []
    failures: list[str] = []

    for response in responses:
        if response is None:
            failures.append("A batch did not return a planning response; candidates from that batch were not adjudicated.")
            continue
        for proposal in response.candidates:
            primary = proposal.primary_component.replace("\\", "/").lstrip("./")
            if primary not in allowed_paths:
                failures.append(f"{primary}: no indexed reference supplied to the model")
                continue
            local_claim_ids = list(dict.fromkeys(proposal.document_claim_ids))
            unknown = [claim_id for claim_id in local_claim_ids if claim_id not in claims_by_local_id]
            if unknown:
                failures.append(f"{primary}: unknown claim IDs: {', '.join(unknown)}")
                continue
            file_record = path_to_file.get(primary)
            target_symbols = planning["symbols_by_file"].get(file_record.id, []) if file_record else []
            symbol = _valid_symbol(target_symbols, proposal.symbol_name)
            if proposal.symbol_name and symbol is False:
                failures.append(f"{primary}: symbol_name is not indexed in the primary component")
                continue
            claim_ids = [claims_by_id[local_id] for local_id in local_claim_ids]
            consumers = planning["consumers_by_path"].get(primary, [])
            provisional.append({
                "proposal_id": f"proposal-{len(provisional) + 1}",
                "proposal": proposal.model_copy(update={
                    "primary_component": primary,
                    "document_claim_ids": claim_ids,
                }),
                "symbol_id": symbol.id if symbol is not None else "",
                "symbol_name": symbol.name if symbol is not None else None,
                "symbol_kind": symbol.kind if symbol is not None else None,
                "claim_ids": claim_ids,
                "consumers": consumers,
                "score": _score_proposal(proposal, len(claim_ids), len(consumers), symbol is not None),
            })
    return provisional, failures, len(failures)


def _consolidation_context(planning: Mapping[str, Any], provisional) -> dict[str, Any]:
    used_claim_ids = {claim_id for item in provisional for claim_id in item["claim_ids"]}
    claims = [claim for index, claim in enumerate(planning["claims"])
        if claim["id"] in used_claim_ids]
    return {
        "objective": planning["objective"],
        "budget": {"max_investigations": planning["max_investigations"]},
        "provisional_candidates": [item["proposal"].model_copy(update={
            "document_claim_ids": item["claim_ids"],
        }).model_dump() | {"source_proposal_ids": [item["proposal_id"]]} for item in provisional],
        "claims": [
            {
                "id": item["id"],
                "category": item["category"],
                "subject": item["subject"],
                "statement": item["statement"],
                "related_subjects": item["related_subjects"],
                "certainty": item["certainty"],
                "constraint": item["constraint"],
            }
            for item in claims
        ],
        "limitations": planning["limitations"],
    }


def _memory_from_responses(planning: Mapping[str, Any], responses):
    accepted, _failures, _rejected = _structural_provisional(planning, responses)
    return [{
        "path": item["proposal"].primary_component,
        "symbol_name": item["symbol_name"],
        "variation_mechanism": item["proposal"].variation_mechanism,
        "alternatives": item["proposal"].alternatives,
        "documented_capability": item["proposal"].documented_capability,
        "variation_basis": item["proposal"].variation_basis,
        "variation_status": item["proposal"].variation_status,
        "document_claim_ids": item["claim_ids"],
    } for item in sorted(accepted, key=lambda item: -item["score"])[:planning["max_investigations"]]]


def _finalize_consolidation(planning: Mapping[str, Any],
                            response: ParametrizationConsolidationResponse | None,
                            provisional: list[dict] | None = None) -> tuple[list[dict], list[str], dict[str, int]]:
    claims_by_id = {claim["id"]: claim for claim in planning["claims"]}
    path_to_file = {file.path: file for file in planning["files"].values()}
    references = {item["path"]: item for item in planning["code_references"]}
    provisional_by_id = {item["proposal_id"]: item for item in provisional} if provisional is not None else None
    accepted: list[dict] = []
    failures: list[str] = []
    host_rejected = 0
    model_excluded = len(response.exclusions) if response is not None else 0

    if response is None:
        failures.append("Global semantic consolidation did not return a response; provisional candidates were withheld.")
        return [], failures, {"host_rejected": 0, "model_excluded": model_excluded}

    for proposal in response.candidates:
        primary = proposal.primary_component.replace("\\", "/").lstrip("./")
        if primary not in references:
            failures.append(f"{primary}: no indexed reference supplied to the consolidator")
            host_rejected += 1
            continue
        source_ids = list(dict.fromkeys(proposal.source_proposal_ids))
        if provisional_by_id is not None:
            unknown_sources = [source_id for source_id in source_ids if source_id not in provisional_by_id]
            if unknown_sources or any(provisional_by_id[source_id]["proposal"].primary_component != primary
                for source_id in source_ids):
                failures.append(f"{primary}: consolidation references an unrelated provisional proposal")
                host_rejected += 1
                continue
        unknown = [claim_id for claim_id in proposal.document_claim_ids if claim_id not in claims_by_id]
        if unknown:
            failures.append(f"{primary}: unknown claim IDs: {', '.join(unknown)}")
            host_rejected += 1
            continue
        if proposal.variation_status != "documented":
            failures.append(f"{primary}: variation is not documented as current or supported")
            host_rejected += 1
            continue

        file_record = path_to_file.get(primary)
        target_symbols = planning["symbols_by_file"].get(file_record.id, []) if file_record else []
        symbol = _valid_symbol(target_symbols, proposal.symbol_name)
        if proposal.symbol_name and symbol is False:
            failures.append(f"{primary}: symbol_name is not indexed in the primary component")
            host_rejected += 1
            continue

        claim_ids = list(dict.fromkeys(proposal.document_claim_ids))
        proposal = proposal.model_copy(update={"primary_component": primary,
            "document_claim_ids": claim_ids})
        consumers = planning["consumers_by_path"].get(primary, [])
        accepted.append({
            "proposal": proposal,
            "symbol_id": symbol.id if symbol is not None else "",
            "symbol_name": symbol.name if symbol is not None else None,
            "symbol_kind": symbol.kind if symbol is not None else None,
            "claim_ids": claim_ids,
            "alternatives": list(dict.fromkeys(proposal.alternatives)),
            "consumers": consumers,
            "score": _score_proposal(proposal, len(claim_ids), len(consumers), symbol is not None),
        })
    return accepted, failures, {"host_rejected": host_rejected, "model_excluded": model_excluded}


def build_parametrization_plan(planning: Mapping[str, Any],
                               response: ParametrizationConsolidationResponse | None,
                               provisional: list[dict] | None = None) -> ParametrizationPlan:
    accepted, failures, diagnostics = _finalize_consolidation(planning, response, provisional)

    ordered = sorted(accepted, key=lambda item: (-item["score"], -len(item["claim_ids"]),
        item["proposal"].primary_component, item["proposal"].variation_mechanism))
    retained = ordered[:planning["max_investigations"]]
    model_excluded = diagnostics["model_excluded"]
    host_rejected = diagnostics["host_rejected"]

    limitations = list(planning["limitations"])
    if model_excluded:
        limitations.append(f"Exclusion diagnostics: the model rejected {model_excluded} plausible option(s).")
    if host_rejected:
        limitations.append(f"Host rejected {host_rejected} semantic proposal(s); unsupported output was withheld.")
    if failures:
        limitations.append(failures[0])
    if len(ordered) > len(retained):
        limitations.append(f"Budget diagnostics: {len(ordered) - len(retained)} valid candidate investigator; discarded beyond configuration.")
    if not retained:
        limitations.append("No sufficiently grounded variation candidate was found; an empty plan is valid.")

    used_claim_ids = {claim_id for item in retained for claim_id in item["claim_ids"]}
    candidates = []
    hypotheses = []
    for item in retained:
        proposal = item["proposal"]
        primary = proposal.primary_component
        consumers = item["consumers"]
        priority = "high" if item["score"] >= 9 else "medium" if item["score"] >= 6 else "low"
        synthesis = proposal.documented_capability.strip().rstrip(".")
        initial_locations = list(dict.fromkeys([primary, *consumers]))[:10]
        candidates.append(ParametrizationCandidate(
            id=create_identifier("investigation", planning["snapshot_hash"], "parametrization",
                primary, item["symbol_id"] or "file", proposal.variation_mechanism),
            priority=priority,
            scope=[primary, *consumers[:2]],
            primary_component=primary,
            symbol_id=item["symbol_id"],
            symbol_name=item["symbol_name"],
            symbol_kind=item["symbol_kind"],
            variation_mechanism=proposal.variation_mechanism,
            alternatives=list(dict.fromkeys(proposal.alternatives)),
            documented_capability=synthesis,
            variation_basis=proposal.variation_basis,
            initial_locations=initial_locations,
            observed_indicators=[
                f"Documented variation: {synthesis}.",
                f"Documented alternatives: {', '.join(proposal.alternatives)}",
                f"Variation basis: {proposal.variation_basis}",
            ],
            question=proposal.question,
            evidence_needed=proposal.evidence_needed,
            document_claim_ids=item["claim_ids"]))
        hypotheses.append(Hypothesis(
            id=candidates[-1].id,
            question=proposal.question,
            criterion_id="parametrized-reuse",
            priority=priority,
            evidence_needed=proposal.evidence_needed))
    claims_by_id = {claim["id"]: claim for claim in planning["claims"]}
    return ParametrizationPlan(
        objectives=[planning["objective"]],
        components=list(dict.fromkeys([item.primary_component for item in candidates]
            + [consumer for candidate in candidates
                for consumer in candidate.initial_locations[1:]])),
        hypotheses=hypotheses,
        candidates=candidates,
        limitations=list(dict.fromkeys(limitations)),
        document_claims={
            claim_id: ParametrizationDocumentClaim.model_validate(claims_by_id[claim_id])
            for claim_id in used_claim_ids if claim_id in claims_by_id
        },
    )

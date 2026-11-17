"""Deterministic output metadata over validated candidates and the retained index.

Never reads source/documents, parses candidate prose, or changes an audit verdict.
An exact indexed import is operationalized only when its consumer and source
window were assessed against an explicit prohibition of that same specifier.
"""

import re
from pathlib import Path

from server.services.document_indexing.service import identifier

from .schemas import FindingVerification, ProhibitedImportDirective

_NEGATIVE_IMPORT = (
    r"(?:\b(?:must|shall|should|may|can)\s+not\s+(?:directly\s+)?import"
    r"|\bprohibited\s+(?:from\s+)?importing"
    r"|\b(?:no|nunca)\s+(?:debe[n]?\s+)?importar"
    r"|\bprohibid[oa]s?\s*:?\s*importar"
    r"|\bning[uú]n\s+[\w -]{1,80}?\s+(?:puede\s+|debe\s+)?importar)"
)
_CONDITIONAL = re.compile(r"\b(?:except|unless|excepto|salvo|excepci[oó]n)\b", re.IGNORECASE)
_IMPORT_KINDS = {"import", "from_import", "reexport", "type_only", "conditional"}


def _prohibits(text, specifier):
    # The token must be the literal operand of a negative import clause. Its
    # occurrence elsewhere, even in quotes or a code example, proves nothing.
    text = text.replace("**", "")
    return bool(re.search(_NEGATIVE_IMPORT + r"\s+[`\"']?" + re.escape(specifier)
        + r"(?![\w/@.\-])(?:[`\"']|(?=\s|[,;.:│]|$))", text, re.IGNORECASE))


def build_verification(candidate, state, snapshot, references):
    """Return a typed directive or explicit abstention, without scope fallbacks."""
    reasons, grouped = [], {}
    if not candidate.document_claim_ids:
        return None, ["verification:no_document_claim: candidate has no explicit documentary backing."]
    files = {file.id: file for file in snapshot.files}
    owners = {key: key for key in files} | {symbol.id: symbol.file_id for symbol in snapshot.symbols}
    paths = {file.path for file in files.values()}
    if not set(candidate.components) <= paths:
        return None, ["verification:non_snapshot_component: components must be real snapshot files."]
    index_evidence = {ref.id: ref for ref in snapshot.evidence}
    origins = state.get("candidate_origins", {}).get(candidate.id, [])
    origin_pairs = {(origin.investigation_id, origin.candidate_id) for origin in origins}
    results = {result.investigation_id: result for result in state["investigation_results"]}
    synthesis = state.get("documentary_synthesis")
    for key in candidate.document_claim_ids:
        prefix = f"verification:{key}:"
        record = state["plan"].document_claims.get(key)
        if record is None or record.status != "applicable" or record.claim.certainty != "explicit":
            reasons.append(prefix + "claim_not_explicit_applicable")
            continue
        if record.claim.constraint != "prohibited":
            reasons.append(prefix + "claim_is_not_an_explicit_prohibition")
            continue
        index = record.document_index
        if (not index or not snapshot.repository.commit or index.commit != snapshot.repository.commit
                or index.repository_id != identifier(str(Path(snapshot.repository.root_path).resolve()))):
            reasons.append(prefix + "incompatible_documentary_provenance")
            continue
        quotes = [item.quote for item in record.claim.evidence]
        if (not quotes or any(not quote for quote in quotes)
                or set(record.claim.section_ids) != set(record.section_paths)):
            reasons.append(prefix + "missing_documentary_quotes_or_sections")
            continue
        if any(_CONDITIONAL.search(text) for text in [record.claim.statement, *quotes]):
            reasons.append(prefix + "conditional_prohibition_requires_exception_resolution")
            continue
        group = synthesis.claims.get(key) if synthesis else None
        rows = []
        for row in group.assessments if group else []:
            result = results.get(row.investigation_id)
            if (row.effective and row.assessment.status == "contradicted" and row.delivery_status == "delivered"
                    and result is not None and result.status == "finding_candidate"
                    and any((result.investigation_id, original.id) in origin_pairs
                            and key in original.document_claim_ids for original in result.candidates)):
                rows.append(row)
        if not rows:
            reasons.append(prefix + "no_validated_contradicted_source_in_candidate_origin")
            continue
        emitted = False
        for row in rows:
            assessment = row.assessment
            source = [references[ref] for ref in assessment.code_evidence_ids
                if ref in references and ref in candidate.evidence_ids and references[ref].kind == "source"
                and references[ref].content_hash and references[ref].tool_call_id
                and references[ref].snapshot_hash == snapshot.repository.snapshot_hash
                and references[ref].commit_verification in {"exact", "line_endings_equivalent"}]
            # Approved cascade: prefer documentary owners, then inspected claim
            # scope, then a single already-inspected component. No broader net.
            consumers = set(candidate.components) & {ref.path for ref in source}
            subjects = set(record.subject_paths)
            if subjects:
                preferred = (consumers & subjects) or (set(assessment.scope_paths) & subjects & set(candidate.components))
            else:
                preferred = set(assessment.scope_paths) & consumers
            if not preferred and len(candidate.components) == 1 and candidate.components[0] in consumers:
                preferred = {candidate.components[0]}
            consumers = preferred - set(record.excluded_paths)
            for relation in snapshot.relationships:
                file = files.get(owners.get(relation.source_id))
                specifier = relation.specifier
                if (file is None or file.path not in consumers or relation.kind not in _IMPORT_KINDS
                        or relation.resolution == "dynamic"
                        or not any(_prohibits(text, specifier)
                                   for text in [record.claim.statement, *quotes])):
                    continue
                anchors = [index_evidence[ref] for ref in relation.evidence_ids if ref in index_evidence]
                if not any(anchor.file_id == file.id and anchor.start_line and anchor.end_line
                    and ref.path == file.path and ref.start_line <= anchor.start_line
                    and anchor.end_line <= ref.end_line for anchor in anchors for ref in source):
                    continue
                permissions = [other for other in state["plan"].document_claims.values()
                    if other.status == "applicable" and other.claim.constraint in {"allowed", "exception"}
                    and file.path in other.scope_paths and (other.claim.constraint == "exception"
                        or specifier in other.claim.statement)]
                if permissions:
                    reasons.append(prefix + f"applicable_permission_or_exception_for:{file.path}")
                    continue
                try:
                    directive = ProhibitedImportDirective(scope=[file.path], targets=[specifier], claim_ids=[key])
                except ValueError:
                    reasons.append(prefix + "indexed_specifier_is_not_a_literal_import_target")
                    continue
                grouped.setdefault((file.path, specifier), set()).update(directive.claim_ids)
                emitted = True
        if not emitted:
            reasons.append(prefix + "no_exact_prohibited_import_with_inspected_consumer_and_import_site")
    directives = [ProhibitedImportDirective(scope=[path], targets=[target], claim_ids=sorted(keys))
                  for (path, target), keys in sorted(grouped.items())]
    return (FindingVerification(directives=directives) if directives else None), sorted(set(reasons))

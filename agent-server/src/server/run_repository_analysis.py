"""Analyze/query a repository in memory. No API credentials or persisted files."""

import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
    RepositoryQueryService,
)
from server.services.repository_analysis.service import RepositoryChangedError

QUERY_NAMES = (
    "overview",
    "projects",
    "files",
    "symbols",
    "dependencies",
    "relationships",
    "entrypoints",
    "architecture",
    "infrastructure",
    "tests",
    "search",
    "source",
    "evidence",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and query a deterministic in-memory repository representation."
    )
    parser.add_argument("root", help="Repository directory")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete structured snapshot (source text excluded by default)",
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        help="Include retained source text in JSON file records",
    )
    parser.add_argument(
        "--query", choices=QUERY_NAMES, help="Print the result of one query as JSON"
    )
    parser.add_argument("--project-id", default=None)
    parser.add_argument(
        "--path",
        default=None,
        help="Exact path for source/symbol queries; prefix for file/search queries",
    )
    parser.add_argument("--name", default=None, help="Symbol or dependency name filter")
    parser.add_argument("--kind", default=None)
    parser.add_argument("--language", default=None)
    parser.add_argument(
        "--resolution",
        default=None,
        choices=("internal", "external", "builtin", "unresolved", "dynamic"),
    )
    parser.add_argument(
        "--source-id",
        default=None,
        help="Relationship origin or symbol id for --query source",
    )
    parser.add_argument("--target-id", default=None)
    parser.add_argument("--evidence-id", default=None)
    parser.add_argument("--text", default=None, help="Literal text for --query search")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--end-line", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--max-depth", type=int, default=30)
    parser.add_argument("--max-file-bytes", type=int, default=2_000_000)
    parser.add_argument("--max-total-bytes", type=int, default=64_000_000)
    return parser


def execute_query(query_service: RepositoryQueryService, arguments):
    pagination = {"offset": arguments.offset, "limit": arguments.limit}
    project_filter = {"project_id": arguments.project_id}
    if arguments.query == "overview":
        return query_service.get_repository_overview()
    if arguments.query == "projects":
        return query_service.list_projects(**pagination)
    if arguments.query == "files":
        return query_service.list_files(
            path_prefix=arguments.path,
            language=arguments.language,
            **project_filter,
            **pagination,
        )
    if arguments.query == "symbols":
        return query_service.find_symbols(
            name=arguments.name,
            kind=arguments.kind,
            file_path=arguments.path,
            **project_filter,
            **pagination,
        )
    if arguments.query == "dependencies":
        return query_service.get_dependencies(
            name=arguments.name, **project_filter, **pagination
        )
    if arguments.query == "relationships":
        return query_service.list_relationships(
            kind=arguments.kind,
            resolution=arguments.resolution,
            source_id=arguments.source_id,
            target_id=arguments.target_id,
            **project_filter,
            **pagination,
        )
    if arguments.query == "entrypoints":
        return query_service.list_entrypoints(
            kind=arguments.kind, **project_filter, **pagination
        )
    if arguments.query == "architecture":
        return query_service.list_architecture_signals(
            kind=arguments.kind, **project_filter, **pagination
        )
    if arguments.query == "infrastructure":
        return query_service.get_infrastructure(
            kind=arguments.kind, **project_filter, **pagination
        )
    if arguments.query == "tests":
        return query_service.get_testing_configuration(**project_filter, **pagination)
    if arguments.query == "search":
        if arguments.text is None:
            raise ValueError("--query search requires --text")
        return query_service.search_repository_text(
            arguments.text, path_prefix=arguments.path, **project_filter, **pagination
        )
    if arguments.query == "source":
        if arguments.source_id:
            return query_service.get_symbol_source(arguments.source_id)
        if arguments.path is None:
            raise ValueError("--query source requires --path or a symbol --source-id")
        return query_service.get_source_excerpt(
            arguments.path, arguments.start_line, arguments.end_line
        )
    if arguments.query == "evidence":
        if arguments.evidence_id is None:
            raise ValueError("--query evidence requires --evidence-id")
        return query_service.get_evidence(arguments.evidence_id)
    raise ValueError(f"Unsupported query: {arguments.query}")


def print_summary(snapshot, elapsed_seconds: float):
    queries = RepositoryQueryService(snapshot)
    print(f"Repository: {snapshot.repository.name}")
    print(f"Root: {snapshot.repository.root_path}")
    print(f"Commit: {snapshot.repository.commit or 'not available'}")
    print(f"Snapshot: {snapshot.repository.snapshot_hash}")
    print(f"Analysis: {elapsed_seconds:.2f}s; deterministic, in memory, no LLM calls")
    print(f"\nTechnologies ({len(snapshot.technologies)}):")
    for technology in sorted(
        snapshot.technologies,
        key=lambda technology: (
            technology.kind,
            technology.name,
            technology.project_id,
        ),
    ):
        version = (
            technology.resolved_version
            or technology.version_constraint
            or "version not declared"
        )
        print(
            f"  {technology.kind}: {technology.name} | {version} | {technology.detection}"
        )
    print(
        f"\nStructure: {len(snapshot.projects)} projects, {len(snapshot.directories)} directories, {len(snapshot.files)} files, {len(snapshot.symbols)} symbols"
    )
    for project in queries.list_projects(limit=10).items:
        print(f"  {project.path}: {project.name} ({project.ecosystem})")
    relationship_counts = Counter(
        relationship.resolution
        for relationship in snapshot.relationships
        if relationship.kind != "contains"
    )
    declared_count = sum(
        dependency.detection == "declared" and dependency.scope != "transitive"
        for dependency in snapshot.dependencies
    )
    print(
        f"\nDependencies: {declared_count} direct declarations, {len(snapshot.dependencies)} total dependency records"
    )
    print(f"  Relationships: {dict(sorted(relationship_counts.items()))}")
    print(f"\nArchitecture signals ({len(snapshot.architecture_signals)}):")
    for signal in queries.list_architecture_signals(limit=10).items:
        print(f"  {signal.kind}: {signal.name} ({signal.detection})")
    print(f"\nEntrypoints ({len(snapshot.entrypoints)}):")
    for entrypoint in queries.list_entrypoints(limit=10).items:
        route = (
            f" {entrypoint.http_method or '*'} {entrypoint.route}"
            if entrypoint.route is not None
            else ""
        )
        print(f"  {entrypoint.kind}: {entrypoint.name}{route} -> {entrypoint.target}")
    print(f"\nInfrastructure ({len(snapshot.infrastructure)}):")
    for resource in queries.get_infrastructure(limit=10).items:
        print(
            f"  {resource.kind}: {resource.name} | {resource.image or resource.build_context or resource.detection}"
        )
    print(f"\nTesting ({len(snapshot.testing)} configurations):")
    for configuration in snapshot.testing:
        print(
            f"  {configuration.framework or 'framework not identified'}: {len(configuration.file_paths)} files; {len(configuration.configuration_paths)} configuration files"
        )
        for command in configuration.commands[:5]:
            print(f"    command: {command}")
    print(
        f"\nCoverage: {snapshot.coverage.processed_files}/{snapshot.coverage.discovered_files} files processed; {snapshot.coverage.retained_bytes} retained bytes"
    )
    print(
        f"  File statuses: {dict(sorted(Counter(source_file.status for source_file in snapshot.files).items()))}"
    )
    print(f"  Issues: {len(snapshot.coverage.issues)}")
    for issue in snapshot.coverage.issues[:10]:
        print(f"    {issue.path}: {issue.category} — {issue.message}")
    if snapshot.coverage.unsupported_source_languages:
        print(
            f"  Languages without deep extraction: {', '.join(snapshot.coverage.unsupported_source_languages)}"
        )


def main(argv=None) -> int:
    arguments = build_parser().parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        options = RepositoryAnalysisInput(
            root_path=arguments.root,
            max_files=arguments.max_files,
            max_depth=arguments.max_depth,
            max_file_bytes=arguments.max_file_bytes,
            max_total_bytes=arguments.max_total_bytes,
        )
        started = time.perf_counter()
        snapshot = RepositoryAnalysisService().analyze_sync(options)
        elapsed_seconds = time.perf_counter() - started
        if arguments.query:
            result = execute_query(RepositoryQueryService(snapshot), arguments)
            excluded_fields = (
                {}
                if arguments.include_source or arguments.query != "files"
                else {"items": {"__all__": {"content"}}}
            )
            print(
                json.dumps(
                    result.model_dump(mode="json", exclude=excluded_fields), indent=2
                )
            )
        elif arguments.json:
            excluded_fields = (
                {} if arguments.include_source else {"files": {"__all__": {"content"}}}
            )
            print(
                json.dumps(
                    snapshot.model_dump(mode="json", exclude=excluded_fields), indent=2
                )
            )
        else:
            print_summary(snapshot, elapsed_seconds)
        return 0
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except (ValueError, KeyError, ValidationError, RepositoryChangedError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

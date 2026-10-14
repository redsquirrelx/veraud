"""Typed, paginated queries over one immutable snapshot; no filesystem reads."""

import posixpath

from .schemas import (
    ArchitectureSignal,
    DependencyRecord,
    EntrypointRecord,
    EvidenceRecord,
    InfrastructureRecord,
    ProjectRecord,
    QueryPage,
    RelationshipRecord,
    RepositoryOverview,
    RepositorySnapshot,
    SourceExcerpt,
    SourceFile,
    SymbolRecord,
    TestConfiguration,
    TextSearchMatch,
)


def query_page(items, offset: int, limit: int):
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError(
            "offset must be non-negative and limit must be between 1 and 500"
        )
    ordered_items = tuple(items)
    return QueryPage(
        items=ordered_items[offset : offset + limit],
        total=len(ordered_items),
        offset=offset,
        limit=limit,
    )


class RepositoryQueryService:
    def __init__(self, snapshot: RepositorySnapshot):
        self.snapshot = snapshot
        self._files_by_path = {
            source_file.path: source_file for source_file in snapshot.files
        }
        self._files_by_id = {
            source_file.id: source_file for source_file in snapshot.files
        }
        self._symbols_by_id = {symbol.id: symbol for symbol in snapshot.symbols}
        self._evidence_by_id = {evidence.id: evidence for evidence in snapshot.evidence}

    def get_repository_overview(self) -> RepositoryOverview:
        return RepositoryOverview(
            repository=self.snapshot.repository,
            project_count=len(self.snapshot.projects),
            file_count=len(self.snapshot.files),
            symbol_count=len(self.snapshot.symbols),
            dependency_count=len(self.snapshot.dependencies),
            relationship_count=len(self.snapshot.relationships),
            technologies=self.snapshot.technologies,
            entrypoint_count=len(self.snapshot.entrypoints),
            infrastructure_count=len(self.snapshot.infrastructure),
            test_configuration_count=len(self.snapshot.testing),
            coverage=self.snapshot.coverage,
        )

    def list_projects(self, *, offset=0, limit=50) -> QueryPage[ProjectRecord]:
        return query_page(
            sorted(self.snapshot.projects, key=lambda project: project.path),
            offset,
            limit,
        )

    def list_files(
        self,
        *,
        project_id=None,
        path_prefix=None,
        language=None,
        status=None,
        offset=0,
        limit=50,
    ) -> QueryPage[SourceFile]:
        return query_page(
            (
                source_file
                for source_file in self.snapshot.files
                if (project_id is None or source_file.project_id == project_id)
                and (path_prefix is None or source_file.path.startswith(path_prefix))
                and (language is None or source_file.language == language)
                and (status is None or source_file.status == status)
            ),
            offset,
            limit,
        )

    def find_symbols(
        self,
        *,
        name=None,
        kind=None,
        project_id=None,
        file_path=None,
        offset=0,
        limit=50,
    ) -> QueryPage[SymbolRecord]:
        symbols = sorted(
            self.snapshot.symbols,
            key=lambda symbol: (
                self._files_by_id[symbol.file_id].path,
                symbol.start_line,
                symbol.qualified_name,
            ),
        )
        return query_page(
            (
                symbol
                for symbol in symbols
                if (name is None or name.casefold() in symbol.qualified_name.casefold())
                and (kind is None or symbol.kind == kind)
                and (project_id is None or symbol.project_id == project_id)
                and (
                    file_path is None
                    or self._files_by_id[symbol.file_id].path == file_path
                )
            ),
            offset,
            limit,
        )

    def get_source_excerpt(
        self, path: str, start_line: int = 1, end_line: int | None = None
    ) -> SourceExcerpt:
        normalized_path = posixpath.normpath(path.replace("\\", "/"))
        source_file = self._files_by_path.get(normalized_path)
        if source_file is None:
            raise KeyError(f"File is not present in this snapshot: {path}")
        if source_file.content is None:
            raise ValueError(
                f"Source was not retained for {path}: {source_file.status}"
            )
        source_lines = source_file.content.splitlines()
        end_line = len(source_lines) if end_line is None else end_line
        if not 1 <= start_line <= end_line <= len(source_lines):
            raise ValueError(
                f"Requested lines are outside retained source: {path} has {len(source_lines)} lines"
            )
        return SourceExcerpt(
            file_id=source_file.id,
            path=source_file.path,
            start_line=start_line,
            end_line=end_line,
            content="\n".join(source_lines[start_line - 1 : end_line]),
            content_hash=source_file.content_hash,
        )

    def get_symbol_source(self, symbol_id: str) -> SourceExcerpt:
        symbol = self._symbols_by_id.get(symbol_id)
        if symbol is None:
            raise KeyError(f"Symbol is not present in this snapshot: {symbol_id}")
        return self.get_source_excerpt(
            self._files_by_id[symbol.file_id].path, symbol.start_line, symbol.end_line
        )

    def get_dependencies(
        self, *, project_id=None, scope=None, name=None, offset=0, limit=50
    ) -> QueryPage[DependencyRecord]:
        dependencies = sorted(
            self.snapshot.dependencies,
            key=lambda dependency: (
                dependency.project_id,
                dependency.name,
                dependency.scope,
            ),
        )
        return query_page(
            (
                dependency
                for dependency in dependencies
                if (project_id is None or dependency.project_id == project_id)
                and (scope is None or dependency.scope == scope)
                and (name is None or name.casefold() in dependency.name.casefold())
            ),
            offset,
            limit,
        )

    def list_relationships(
        self,
        *,
        project_id=None,
        kind=None,
        resolution=None,
        source_id=None,
        target_id=None,
        offset=0,
        limit=50,
    ) -> QueryPage[RelationshipRecord]:
        return query_page(
            (
                relationship
                for relationship in self.snapshot.relationships
                if (project_id is None or relationship.project_id == project_id)
                and (kind is None or relationship.kind == kind)
                and (resolution is None or relationship.resolution == resolution)
                and (source_id is None or relationship.source_id == source_id)
                and (target_id is None or relationship.target_id == target_id)
            ),
            offset,
            limit,
        )

    def get_outgoing_relationships(
        self, entity_id: str, *, offset=0, limit=50
    ) -> QueryPage[RelationshipRecord]:
        return self.list_relationships(source_id=entity_id, offset=offset, limit=limit)

    def get_incoming_relationships(
        self, entity_id: str, *, offset=0, limit=50
    ) -> QueryPage[RelationshipRecord]:
        return self.list_relationships(target_id=entity_id, offset=offset, limit=limit)

    def list_entrypoints(
        self, *, project_id=None, kind=None, offset=0, limit=50
    ) -> QueryPage[EntrypointRecord]:
        return query_page(
            (
                entrypoint
                for entrypoint in sorted(
                    self.snapshot.entrypoints,
                    key=lambda entrypoint: (
                        entrypoint.target,
                        entrypoint.name,
                        entrypoint.id,
                    ),
                )
                if (project_id is None or entrypoint.project_id == project_id)
                and (kind is None or entrypoint.kind == kind)
            ),
            offset,
            limit,
        )

    def list_architecture_signals(
        self, *, project_id=None, kind=None, offset=0, limit=50
    ) -> QueryPage[ArchitectureSignal]:
        return query_page(
            (
                signal
                for signal in sorted(
                    self.snapshot.architecture_signals,
                    key=lambda signal: (signal.kind, signal.name),
                )
                if (project_id is None or signal.project_id == project_id)
                and (kind is None or signal.kind == kind)
            ),
            offset,
            limit,
        )

    def get_infrastructure(
        self, *, project_id=None, kind=None, offset=0, limit=50
    ) -> QueryPage[InfrastructureRecord]:
        return query_page(
            (
                resource
                for resource in sorted(
                    self.snapshot.infrastructure,
                    key=lambda resource: (resource.kind, resource.name),
                )
                if (project_id is None or resource.project_id == project_id)
                and (kind is None or resource.kind == kind)
            ),
            offset,
            limit,
        )

    def get_testing_configuration(
        self, *, project_id=None, offset=0, limit=50
    ) -> QueryPage[TestConfiguration]:
        return query_page(
            (
                configuration
                for configuration in self.snapshot.testing
                if project_id is None or configuration.project_id == project_id
            ),
            offset,
            limit,
        )

    def get_evidence(self, evidence_id: str) -> EvidenceRecord:
        evidence = self._evidence_by_id.get(evidence_id)
        if evidence is None:
            raise KeyError(f"Evidence is not present in this snapshot: {evidence_id}")
        return evidence

    def search_repository_text(
        self,
        query: str,
        *,
        project_id=None,
        path_prefix=None,
        case_sensitive=False,
        offset=0,
        limit=50,
    ) -> QueryPage[TextSearchMatch]:
        if not query.strip():
            raise ValueError("Search query must not be empty")
        search_term = query if case_sensitive else query.casefold()
        matches = []
        for source_file in self.snapshot.files:
            if (
                source_file.content is None
                or project_id is not None
                and source_file.project_id != project_id
                or path_prefix is not None
                and not source_file.path.startswith(path_prefix)
            ):
                continue
            for line_number, line in enumerate(source_file.content.splitlines(), 1):
                if search_term in (line if case_sensitive else line.casefold()):
                    matches.append(
                        TextSearchMatch(
                            file_id=source_file.id,
                            path=source_file.path,
                            line=line_number,
                            text=line,
                        )
                    )
        return query_page(matches, offset, limit)

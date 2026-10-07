from pydantic import BaseModel, Field


class DependencyGraphInput(BaseModel):
    """What to map and how deep."""

    root_path: str = Field(
        description="Directory to map, e.g. appdata/workspace/{id}-{owner}-{repo}",
    )
    max_depth: int = Field(
        default=8,
        ge=1,
        description="Maximum directory depth to walk",
    )
    max_files: int = Field(
        default=500,
        ge=1,
        description="Maximum files to include before truncating",
    )
    include_external: bool = Field(
        default=False,
        description="Keep edges pointing outside the repo (third-party imports)",
    )
    detect_cycles: bool = Field(
        default=True,
        description="Compute circular import groups",
    )


class ImportEdge(BaseModel):
    """One import statement in one file."""

    source: str = Field(description="Importing file, repo-relative, POSIX")
    target: str | None = Field(
        default=None,
        description="Imported file, repo-relative. None when not internal.",
    )
    specifier: str = Field(
        description="Dotted name as written in code, e.g. '..app.agent_registry'",
    )
    kind: str = Field(
        description=(
            "import | from_import | reexport | type_only | conditional | dynamic"
        ),
    )
    resolved: bool = Field(
        description="True when target is a file inside the repo",
    )
    reason: str | None = Field(
        default=None,
        description="Why unresolved: external | not_found | too_many_dots | dynamic_expr",
    )
    level: int = Field(default=0, ge=0, description="Leading dots, 0 for absolute")
    line: int = Field(default=0, ge=0, description="1-based line of the statement")


class DependencyGraphStats(BaseModel):
    files: int = Field(ge=0, description="Python files indexed")
    edges: int = Field(ge=0, description="Edges kept in the output")
    internal: int = Field(ge=0)
    external: int = Field(ge=0, description="Distinct third-party specifiers referenced")
    unresolved: list[str] = Field(
        default_factory=list,
        description="Specifiers that could be local but were not found: file|specifier",
    )
    dynamic: int = Field(ge=0, description="importlib/__import__ calls, not statically resolvable")
    truncated: bool = Field(default=False)
    cycles: list[list[str]] = Field(
        default_factory=list,
        description="Circular import groups, each a list of repo-relative files",
    )


class DependencyGraphOutput(BaseModel):
    """Which repo file depends on which."""

    root: str = Field(description="Absolute root that was mapped")
    edges: list[ImportEdge] = Field(default_factory=list)
    stats: DependencyGraphStats
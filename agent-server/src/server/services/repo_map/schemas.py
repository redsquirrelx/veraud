from pydantic import BaseModel, Field


class RepoMapInput(BaseModel):
    """What to map and how deep."""

    root_path: str = Field(
        description="Directory to map, e.g. appdata/workspace/{id}-{owner}-{repo}",
    )
    max_depth: int = Field(
        default=4,
        ge=1,
        description="Maximum directory depth to descend",
    )
    max_files: int = Field(
        default=300,
        ge=1,
        description="Maximum files to include before truncating",
    )
    include_symbols: bool = Field(
        default=True,
        description="Parse Python files and list their classes and functions",
    )


class Symbol(BaseModel):
    """One definition found in a source file."""

    name: str
    kind: str = Field(
        description="Role in its own language: class, function, method, struct, ...",
    )
    line: int = Field(ge=1, description="1-based line where the definition starts")
    signature: str | None = Field(
        default=None,
        description="Rendered signature, functions and methods only",
    )


class RepoFile(BaseModel):
    """A single mapped file."""

    path: str = Field(description="Path relative to the mapped root, POSIX separators")
    language: str = Field(description="Detected language: python, markdown, yaml, ...")
    size_bytes: int = Field(ge=0)
    lines: int | None = Field(default=None, description="Line count, text files only")
    symbols: list[Symbol] = Field(default_factory=list)


class RepoMapStats(BaseModel):
    total_files: int = Field(ge=0, description="Files found under the root before limits")
    included_files: int = Field(ge=0)
    truncated: bool = Field(default=False)
    total_lines: int = Field(default=0, ge=0)


class RepoMapOutput(BaseModel):
    """The map itself: a rendered tree plus the structured entries."""

    root: str = Field(description="Absolute root that was mapped")
    tree: str = Field(description="Rendered tree, ready to paste into a prompt")
    files: list[RepoFile] = Field(default_factory=list)
    stats: RepoMapStats
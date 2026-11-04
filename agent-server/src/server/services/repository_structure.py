"""Repository structure extraction through the local, code-only Graphify adapter."""

from pathlib import Path

from server.services.graphify import GraphifyAdapter, GraphifyResult


class RepositoryStructureService:
    """Generate a structural graph without models or agent execution.

    The result references Graphify's artifact, not a normalized internal schema.
    Output ownership, path restrictions and safe failures follow the adapter.
    """

    def __init__(self, adapter: GraphifyAdapter | None = None) -> None:
        self._adapter = adapter if adapter is not None else GraphifyAdapter()

    async def extract_structure(
        self, repository_path: Path, output_directory: Path
    ) -> GraphifyResult:
        return await self._adapter.extract(
            repository_path=repository_path,
            output_directory=output_directory,
        )

from ...config.logs import get_logger
from ..dependency_graph.schemas import DependencyGraphInput
from ..dependency_graph.service import DependencyGraphService
from ..repo_map.schemas import RepoMapInput
from ..repo_map.service import RepoMapService
from .schemas import Collection, CollectionInput

logger = get_logger("service.collection")


class CollectionService:
    """Runs every representation over one repository and returns the results.

    Collects only. It never labels, scores or judges: the output is a bag of
    observable facts, and deciding what they mean is the caller's job.

    Representations are pure functions of the files on disk, so there is
    nothing to persist and nothing to invalidate. Running this twice on an
    unchanged repo gives the same answer.
    """

    def __init__(
        self,
        repo_map: RepoMapService | None = None,
        dependency_graph: DependencyGraphService | None = None,
    ) -> None:
        self._repo_map = repo_map or RepoMapService()
        self._dependency_graph = dependency_graph or DependencyGraphService()

    @property
    def representations(self) -> tuple[str, ...]:
        return ("repo_map", "dependency_graph")

    async def collect(self, input_data: CollectionInput) -> Collection:
        root = input_data.root_path

        logger.info("Collecting representations for %s", root)

        repo_map = await self._repo_map.create(RepoMapInput(
            root_path=root,
            max_depth=input_data.max_depth,
            max_files=input_data.max_files,
        ))

        dependency_graph = await self._dependency_graph.create(DependencyGraphInput(
            root_path=root,
            max_depth=input_data.max_depth,
            max_files=input_data.max_files,
            include_external=input_data.include_external,
        ))

        stats = {
            "representations": list(self.representations),
            "files": dependency_graph.stats.files,
            "repo_map_files": repo_map.stats.included_files,
            "repo_map_lines": repo_map.stats.total_lines,
            "internal_edges": dependency_graph.stats.internal,
            "external": dependency_graph.stats.external,
            "unresolved": len(dependency_graph.stats.unresolved),
            "dynamic_imports": dependency_graph.stats.dynamic,
            "cycles": len(dependency_graph.stats.cycles),
            "truncated": repo_map.stats.truncated or dependency_graph.stats.truncated,
        }

        logger.info(
            "Collected files=%d lines=%d edges=%d cycles=%d",
            stats["files"], stats["repo_map_lines"],
            stats["internal_edges"], stats["cycles"],
        )

        return Collection(
            root=repo_map.root,
            repo_map=repo_map.model_dump(),
            dependency_graph=dependency_graph.model_dump(),
            stats=stats,
        )
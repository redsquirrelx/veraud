"""Bounded text and AST search over the repository."""

import ast
import re
from pathlib import Path

from .fs_guard import is_excluded, resolve_within
from .package_discovery import package_of
from .repo_reader import PathSafetyError


def _python_files(base: Path):
    if base.is_file() and base.suffix == ".py":
        yield base
        return
    for candidate in sorted(base.rglob("*.py")):
        if candidate.is_file():
            yield candidate


class CodeSearch:
    def __init__(self, repo_root: str | Path, *, max_results: int = 50):
        self.root = Path(repo_root).resolve()
        self.max_results = max_results

    def search_text(self, query: str, scope: str = ".", limit: int = 20, regex: bool = False) -> list[dict]:
        if not query:
            raise ValueError("query must not be empty")
        if limit < 1 or limit > self.max_results:
            raise ValueError(f"limit must be between 1 and {self.max_results}")
        scope_path = resolve_within(self.root, scope or ".")
        pattern = re.compile(query if regex else re.escape(query))
        results: list[dict] = []
        for path in self._iter_files(scope_path):
            if len(results) >= limit:
                break
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(content.splitlines(), start=1):
                if len(results) >= limit:
                    break
                if pattern.search(line):
                    results.append({"path": path.relative_to(self.root).as_posix(),
                                    "line": lineno, "text": line.rstrip()})
        return results

    def find_imports(self, module_prefix: str, scope: str = ".", limit: int = 100) -> list[dict]:
        """AST search: every import whose resolved absolute module starts with `module_prefix`."""
        scope_path = resolve_within(self.root, scope or ".")
        results: list[dict] = []
        for path in _python_files(scope_path):
            if is_excluded(path.relative_to(self.root)):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            package = package_of(path.relative_to(self.root).as_posix())
            for node in ast.walk(tree):
                if len(results) >= limit:
                    return results
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == module_prefix or alias.name.startswith(module_prefix + "."):
                            results.append({"path": path.relative_to(self.root).as_posix(),
                                            "line": node.lineno, "module": alias.name})
                elif isinstance(node, ast.ImportFrom):
                    base = _resolve_from(package, node.module, node.level)
                    dotted = ".".join(part for part in base if part)
                    candidates = [dotted] + [".".join([*base, alias.name]) for alias in node.names if alias.name != "*"]
                    for candidate in candidates:
                        if candidate == module_prefix or candidate.startswith(module_prefix + "."):
                            results.append({"path": path.relative_to(self.root).as_posix(),
                                            "line": node.lineno, "module": candidate})
                            break
        return results

    def _iter_files(self, scope_path: Path):
        if scope_path.is_file():
            yield scope_path
            return
        for candidate in sorted(scope_path.rglob("*")):
            if candidate.is_file():
                relative = candidate.relative_to(self.root)
                if not is_excluded(relative):
                    yield candidate


def _resolve_from(package: list[str], module: str | None, level: int) -> list[str]:
    if level == 0:
        return (module or "").split(".") if module else []
    base = package[: len(package) - (level - 1)] if level > 1 else list(package)
    return base + ((module or "").split(".") if module else [])


__all__ = ["CodeSearch", "PathSafetyError"]

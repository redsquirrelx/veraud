"""Shared helpers for the Tallercito verification suite."""

import ast
import os
from pathlib import Path


def repo_root() -> Path:
    override = os.environ.get("TALLERCITO_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _module_parts(component) -> list[str]:
    parts = [part for part in component.split("/") if part]
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
        if parts[-1] == "__init__":
            parts.pop()
    for index, part in enumerate(parts):
        if part == "src":
            return parts[index + 1:]
    return parts


def _package_parts(relative: Path) -> list[str]:
    return _module_parts(relative.as_posix())[:-1]


def _resolve_import_from(package: list[str], module: str | None, level: int) -> list[str]:
    if level == 0:
        return (module or "").split(".") if module else []
    base = package[: len(package) - (level - 1)] if level > 1 else list(package)
    return base + ((module or "").split(".") if module else [])


def imported_modules(file: Path, root: Path) -> list[tuple[int, str]]:
    relative = file.relative_to(root)
    package = _package_parts(relative)
    tree = ast.parse(file.read_text(encoding="utf-8"))
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(package, node.module, node.level)
            dotted = ".".join(part for part in base if part)
            if dotted:
                imports.append((node.lineno, dotted))
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = ".".join([*base, alias.name])
                imports.append((node.lineno, candidate))
    return imports


def import_aliases(file: Path, root: Path) -> dict[str, str]:
    """Map local alias name -> absolute dotted module."""
    relative = file.relative_to(root)
    package = _package_parts(relative)
    tree = ast.parse(file.read_text(encoding="utf-8"))
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                aliases[name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(package, node.module, node.level)
            resolved = ".".join(part for part in base if part)
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = resolved + "." + alias.name if resolved else alias.name
    return aliases


def _matches(dotted: str, forbidden: str) -> bool:
    return dotted == forbidden or dotted.startswith(forbidden + ".")


def _files_in_scope(scope):
    root = repo_root()
    target = root / scope
    if target.is_dir():
        return sorted(target.rglob("*.py")), root
    if target.is_file():
        return [target], root
    return [], root


def _unparsed_offender(relative: Path, root: Path) -> str:
    return f"{relative.as_posix()}: unparseable source"


def scan_scope(scope: str, forbidden_roots, allowed_exceptions=()) -> list[str]:
    offenders: list[str] = []
    files, root = _files_in_scope(scope)
    if not files:
        raise RuntimeError(f"NOT_VERIFIABLE: source scope not found: {scope}")
    for path in files:
        if path.name in allowed_exceptions:
            continue
        try:
            entries = imported_modules(path, root)
        except SyntaxError:
            offenders.append(_unparsed_offender(path.relative_to(root), root))
            continue
        for line, dotted in entries:
            for forbidden in forbidden_roots:
                if _matches(dotted, forbidden):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{line} imports {dotted}")
    return offenders


def restricted_import_check(scope: str, allowed_roots) -> list[str]:
    offenders: list[str] = []
    files, root = _files_in_scope(scope)
    if not files:
        raise RuntimeError(f"NOT_VERIFIABLE: source scope not found: {scope}")
    for path in files:
        try:
            entries = imported_modules(path, root)
        except SyntaxError:
            offenders.append(_unparsed_offender(path.relative_to(root), root))
            continue
        for line, dotted in entries:
            if not any(_matches(dotted, allowed) for allowed in allowed_roots):
                offenders.append(f"{path.relative_to(root).as_posix()}:{line} imports {dotted}")
    return offenders


def find_private_module_imports(private_module: str, owning_package: str) -> list[str]:
    root = repo_root()
    owning = (root / owning_package).resolve()
    offenders: list[str] = []
    for path in sorted((root / "src").rglob("*.py")) if (root / "src").is_dir() else sorted(root.rglob("*.py")):
        resolved = path.resolve()
        if owning == resolved.parent or owning in resolved.parents:
            continue
        try:
            entries = imported_modules(path, root)
        except SyntaxError:
            offenders.append(f"{path.relative_to(root).as_posix()}: unparseable source")
            continue
        for line, dotted in entries:
            if _matches(dotted, private_module):
                offenders.append(f"{path.relative_to(root).as_posix()}:{line} imports {dotted}")
    return offenders


def forbidden_attribute_check(scope: str, module_prefix: str, attr_prefixes=("_",)) -> list[str]:
    """Attribute access to underscored attributes of module matching ``module_prefix``."""
    offenders: list[str] = []
    target_prefix = module_prefix
    files, root = _files_in_scope(scope)
    if not files:
        raise RuntimeError(f"NOT_VERIFIABLE: source scope not found: {scope}")
    for path in files:
        try:
            aliases = import_aliases(path, root)
        except SyntaxError:
            offenders.append(_unparsed_offender(path.relative_to(root), root))
            continue
        if not aliases:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        targets = [alias for alias, dotted in aliases.items() if _matches(dotted, target_prefix)]
        if not targets:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith(tuple(attr_prefixes)):
                if isinstance(node.value, ast.Name) and node.value.id in targets:
                    offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno} accesses {node.value.id}.{node.attr}")
                elif isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id in targets:
                    offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno} accesses {node.value.value.id}.{node.value.attr}.{node.attr}")
    return offenders


def no_environ_in_scope(scope: str) -> list[str]:
    offenders: list[str] = []
    files, root = _files_in_scope(scope)
    if not files:
        raise RuntimeError(f"NOT_VERIFIABLE: source scope not found: {scope}")
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            offenders.append(_unparsed_offender(path.relative_to(root), root))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                func = node.func
                if (isinstance(func.value, ast.Name) and func.value.id == "os"
                        and func.attr in {"getenv", "environ"}):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno} reads os.{func.attr}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"getenv", "environ"}:
                    offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno} reads {node.func.id}")
            elif isinstance(node, ast.Attribute):
                if (isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr == "environ"):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno} reads os.environ")
    return offenders


def _dotted_from_relative(relative: str) -> str:
    return ".".join(_module_parts(relative))


def circular_import_check(scope: str) -> list[str]:
    offenders: set[str] = set()
    files, root = _files_in_scope(scope)
    if not files:
        raise RuntimeError(f"NOT_VERIFIABLE: source scope not found: {scope}")
    imports_by_file: dict[str, list[str]] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            entries = imported_modules(path, root)
        except SyntaxError:
            continue
        imports_by_file[relative] = [entry[1] for entry in entries]
    pairs = list(imports_by_file.items())
    for index, (left, left_imports) in enumerate(pairs):
        left_dotted = _dotted_from_relative(left)
        for right_index in range(index + 1, len(pairs)):
            right, right_imports = pairs[right_index]
            right_dotted = _dotted_from_relative(right)
            left_to_right = any(_matches(dep, right_dotted) for dep in left_imports)
            right_to_left = any(_matches(dep, left_dotted) for dep in right_imports)
            if left_to_right and right_to_left:
                offenders.add(f"{left} <-> {right} (circular import)")
    return sorted(offenders)

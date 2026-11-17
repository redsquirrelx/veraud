"""Shared helpers for discovering the layout-independent dotted module path.

Python projects differ in layout — src layout, flat layout, monorepo packages.
This helper locates the first ``src`` path segment when present; otherwise it
keeps the path from the repository root. It also handles ``__init__.py``
normalization. Namespace packages are supported because no ``__init__.py``
marker is required.
"""



def module_parts(component: str) -> list[str]:
    parts = [part for part in component.replace("\\", "/").split("/") if part]
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
        if parts[-1] == "__init__":
            parts.pop()
    return parts


def dotted_module(component: str) -> str:
    parts = module_parts(component)
    for index, part in enumerate(parts):
        if part == "src":
            parts = parts[index + 1 :]
            break
    return ".".join(parts)


def import_root(component: str) -> str:
    """Dotted import root, capped at two segments (``<package>.<layer>``)."""

    dotted = dotted_module(component)
    parts = dotted.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")


def package_of(relative: str) -> list[str]:
    """Package parts of the importing file, used to resolve relative imports."""

    parts = module_parts(relative)
    for index, part in enumerate(parts):
        if part == "src":
            parts = parts[index + 1 :]
            break
    return parts[:-1] if parts else []

"""Read-only syntactic checks on the exact source excerpts cited by boundary claims."""

import ast
import json
import tomllib
import warnings
from pathlib import PurePosixPath

import tree_sitter_javascript
import tree_sitter_typescript
import yaml
from tree_sitter import Language, Parser


def dependency_span(source, reference):
    """Navigation to the complete import/export intersecting a delivered excerpt.

    This reads the retained snapshot only; the caller must still retrieve the
    returned range through the normal budgeted tools before citing its bytes.
    """
    if reference.kind != "source" or not source.content or reference.start_line is None:
        return None
    suffix = PurePosixPath(source.path).suffix.lower()
    if suffix == ".py":
        try:
            tree = ast.parse(source.content)
        except (SyntaxError, ValueError):
            return None
        spans = [(node.lineno, node.end_lineno) for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))]
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}:
        grammar = (tree_sitter_javascript.language() if suffix in {".js", ".jsx", ".mjs", ".cjs"} else
            tree_sitter_typescript.language_tsx() if suffix == ".tsx" else tree_sitter_typescript.language_typescript())
        tree = Parser(Language(grammar)).parse(source.content.encode("utf-8"))
        spans = []
        # Imports/exports live at module scope; do not treat calls inside a
        # function exported over hundreds of lines as an import declaration.
        for node in tree.root_node.children:
            if node.type == "import_statement" or (node.type == "export_statement"
                    and any(child.type == "string" for child in node.children)):
                spans.append((node.start_point[0] + 1, node.end_point[0] + 1))
    else:
        return None
    return next(((start, end) for start, end in spans
        if start <= reference.end_line and end >= reference.start_line), None)


def supports_role(source, reference, role):
    if reference.kind != "source" or source.content is None or reference.start_line is None:
        return False
    start, end = reference.start_line, reference.end_line
    suffix = PurePosixPath(source.path).suffix.lower()
    if suffix == ".py":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source.content)
        except (SyntaxError, ValueError):
            return False
        types = {
            "declaration": (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom),
            "dependency": (ast.Import, ast.ImportFrom),
            "implementation": (ast.Assign, ast.AugAssign, ast.Return, ast.Raise, ast.Call, ast.If, ast.For, ast.While),
            "usage": (ast.Call,), "composition": (ast.Call,),
        }[role]
        return any(isinstance(node, types) and start <= getattr(node, "lineno", 0) <= end
            for node in ast.walk(tree))
    if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}:
        grammar = (tree_sitter_javascript.language() if suffix in {".js", ".jsx", ".mjs", ".cjs"} else
            tree_sitter_typescript.language_tsx() if suffix == ".tsx" else tree_sitter_typescript.language_typescript())
        language = Language(grammar)
        parser = Parser(language)
        tree = parser.parse(source.content.encode("utf-8"))
        types = {
            "declaration": {"interface_declaration", "type_alias_declaration", "class_declaration", "function_declaration", "lexical_declaration", "import_statement"},
            "dependency": {"import_statement", "export_statement", "call_expression"},
            "implementation": {"call_expression", "assignment_expression", "return_statement", "if_statement", "lexical_declaration"},
            "usage": {"call_expression", "new_expression"},
            "composition": {"call_expression", "new_expression"},
        }[role]
        # Keep native wrappers short-lived while traversing large source files.
        cursor = tree.walk()
        while True:
            node = cursor.node
            # Index the Point tuple, as the inventory does. Repeated .row access
            # on temporary Points corrupts GC state on CPython 3.13/Windows;
            # the access violation can surface later in unrelated validation.
            if node.type in types and start <= node.start_point[0] + 1 <= end:
                return True
            if cursor.goto_first_child():
                continue
            while not cursor.goto_next_sibling():
                if not cursor.goto_parent():
                    return False
    if suffix == ".toml" and role == "declaration":
        excerpt = "\n".join(source.content.splitlines()[start - 1:end])
        try:
            return bool(tomllib.loads(excerpt))
        except tomllib.TOMLDecodeError:
            return False
    if suffix in {".json", ".yaml", ".yml"} and role == "declaration":
        excerpt = "\n".join(source.content.splitlines()[start - 1:end])
        try:
            value = json.loads(excerpt) if suffix == ".json" else yaml.safe_load(excerpt)
            return isinstance(value, (dict, list)) and bool(value)
        except (ValueError, yaml.YAMLError):
            return False
    return False

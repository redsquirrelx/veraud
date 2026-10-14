"""Extract scoped symbols and retained syntax trees for Python and JS/TS."""

import ast
import re
import warnings

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

from .context import AnalysisContext, create_identifier
from .schemas import ArchitectureSignal, SymbolRecord, TechnologyRecord


def python_expression_name(expression: ast.AST) -> str:
    return ast.unparse(expression)


def node_text(node, content_bytes: bytes) -> str:
    return content_bytes[node.start_byte : node.end_byte].decode("utf-8")


def extract_source_code(context: AnalysisContext) -> None:
    language_files: dict[tuple[str, str], list] = {}
    for source_file in context.processed_files():
        language_files.setdefault(
            (source_file.project_id, source_file.language), []
        ).append(source_file)
        if source_file.language == "python":
            try:
                # Repo sources are third-party text: non-raw escapes (e.g. "\d"
                # in a regex written as "\\d") warn at compile time. The AST
                # shape is unaffected, so only that warning is suppressed here.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    syntax_tree = ast.parse(
                        source_file.content, filename=source_file.path
                    )
            except SyntaxError as error:
                context.add_issue(
                    source_file.path,
                    "source_parse_error",
                    f"Python syntax error at line {error.lineno}.",
                )
                continue
            context.python_trees[source_file.path] = syntax_tree
            extract_python_symbols(context, source_file, syntax_tree)
        elif source_file.language in ("javascript", "typescript"):
            grammar = (
                tree_sitter_javascript.language()
                if source_file.language == "javascript"
                else tree_sitter_typescript.language_tsx()
                if source_file.path.endswith(".tsx")
                else tree_sitter_typescript.language_typescript()
            )
            syntax_tree = Parser(Language(grammar)).parse(
                source_file.content.encode("utf-8")
            )
            context.javascript_trees[source_file.path] = syntax_tree
            if syntax_tree.root_node.has_error:
                context.add_issue(
                    source_file.path,
                    "source_parse_error",
                    "Tree-sitter found syntax errors; extracted facts may be partial.",
                )
            extract_javascript_symbols(context, source_file, syntax_tree)
    for (project_id, language), source_files in sorted(language_files.items()):
        if language in (
            "text",
            "json",
            "toml",
            "yaml",
            "markdown",
            "rst",
            "dockerfile",
        ):
            continue
        evidence_ids = tuple(
            context.add_evidence(source_file, "file_language")
            for source_file in source_files
        )
        context.technologies.append(
            TechnologyRecord(
                id=create_identifier("technology", project_id, "language", language),
                project_id=project_id,
                name=language,
                kind="language",
                detection="observed",
                evidence_ids=evidence_ids,
            )
        )


def extract_python_symbols(context: AnalysisContext, source_file, syntax_tree):
    def visit_definitions(parent_node, parent_symbol=None):
        for child_node in ast.iter_child_nodes(parent_node):
            if not isinstance(
                child_node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                visit_definitions(child_node, parent_symbol)
                continue
            qualified_name = (
                f"{parent_symbol.qualified_name}.{child_node.name}"
                if parent_symbol
                else child_node.name
            )
            symbol_kind = (
                "class"
                if isinstance(child_node, ast.ClassDef)
                else "method"
                if parent_symbol and parent_symbol.kind == "class"
                else "function"
            )
            start_line = min(
                [child_node.lineno]
                + [decorator.lineno for decorator in child_node.decorator_list]
            )
            end_line = child_node.end_lineno or child_node.lineno
            decorators = tuple(
                python_expression_name(decorator)
                for decorator in child_node.decorator_list
            )
            base_names = (
                tuple(python_expression_name(base) for base in child_node.bases)
                if isinstance(child_node, ast.ClassDef)
                else ()
            )
            evidence_id = context.add_evidence(
                source_file, "python_symbol", start_line, end_line
            )
            symbol = SymbolRecord(
                id=create_identifier(
                    "symbol", source_file.path, qualified_name, start_line
                ),
                file_id=source_file.id,
                project_id=source_file.project_id,
                name=child_node.name,
                qualified_name=qualified_name,
                kind=symbol_kind,
                start_line=start_line,
                end_line=end_line,
                signature=None
                if symbol_kind == "class"
                else f"{child_node.name}({ast.unparse(child_node.args)})",
                parent_symbol_id=parent_symbol.id if parent_symbol else None,
                base_names=base_names,
                decorators=decorators,
                evidence_ids=(evidence_id,),
            )
            context.symbols.append(symbol)
            visit_definitions(child_node, symbol)

    visit_definitions(syntax_tree)


def extract_javascript_symbols(context: AnalysisContext, source_file, syntax_tree):
    content_bytes = source_file.content.encode("utf-8")
    symbol_kinds = {
        "class_declaration": "class",
        "abstract_class_declaration": "class",
        "interface_declaration": "interface",
        "type_alias_declaration": "type_alias",
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "function_signature": "function",
        "method_definition": "method",
        "method_signature": "method",
    }

    def visit_node(node, parent_symbol=None):
        symbol_kind = symbol_kinds.get(node.type)
        if node.type == "variable_declarator":
            value_node = node.child_by_field_name("value")
            if value_node is not None and value_node.type in (
                "arrow_function",
                "function_expression",
                "generator_function",
            ):
                symbol_kind = "function"
        name_node = node.child_by_field_name("name")
        symbol = None
        if symbol_kind and name_node is not None:
            symbol_name = node_text(name_node, content_bytes)
            qualified_name = (
                f"{parent_symbol.qualified_name}.{symbol_name}"
                if parent_symbol
                else symbol_name
            )
            declaration = (
                node.parent
                if node.parent
                and node.parent.type
                in ("export_statement", "lexical_declaration", "variable_declaration")
                else node
            )
            start_line, end_line = (
                declaration.start_point[0] + 1,
                declaration.end_point[0] + 1,
            )
            if declaration.end_point[1] == 0 and end_line > start_line:
                end_line -= 1
            decorator_nodes = [
                child
                for child in declaration.named_children + node.named_children
                if child.type == "decorator"
            ]
            preceding_node = declaration.prev_named_sibling
            while preceding_node is not None and preceding_node.type == "decorator":
                decorator_nodes.insert(0, preceding_node)
                preceding_node = preceding_node.prev_named_sibling
            if decorator_nodes:
                start_line = min(
                    start_line,
                    *(decorator.start_point[0] + 1 for decorator in decorator_nodes),
                )
            decorators = tuple(
                node_text(child, content_bytes).removeprefix("@")
                for child in decorator_nodes
            )
            base_names = []
            for child in node.named_children:
                if child.type in ("class_heritage", "extends_type_clause"):
                    heritage_text = node_text(child, content_bytes)
                    base_names.extend(
                        name.strip()
                        for name in re.split(
                            r"\bextends\b|\bimplements\b|,", heritage_text
                        )
                        if name.strip()
                    )
            parameters = node.child_by_field_name("parameters")
            if parameters is None and node.type == "variable_declarator":
                value_node = node.child_by_field_name("value")
                parameters = value_node.child_by_field_name("parameters")
            evidence_id = context.add_evidence(
                source_file, "javascript_symbol", start_line, end_line
            )
            symbol = SymbolRecord(
                id=create_identifier(
                    "symbol", source_file.path, qualified_name, start_line
                ),
                file_id=source_file.id,
                project_id=source_file.project_id,
                name=symbol_name,
                qualified_name=qualified_name,
                kind=symbol_kind,
                start_line=start_line,
                end_line=end_line,
                signature=f"{symbol_name}{node_text(parameters, content_bytes)}"
                if parameters
                else None,
                parent_symbol_id=parent_symbol.id if parent_symbol else None,
                base_names=tuple(base_names),
                decorators=tuple(dict.fromkeys(decorators)),
                evidence_ids=(evidence_id,),
            )
            context.symbols.append(symbol)
        for child in node.named_children:
            visit_node(child, symbol or parent_symbol)
        if (
            source_file.path.rsplit("/", 1)[-1].startswith("next.config")
            and node.type == "pair"
        ):
            key_node = node.child_by_field_name("key")
            value_node = node.child_by_field_name("value")
            if (
                key_node is not None
                and value_node is not None
                and value_node.type == "string"
            ):
                key_name = node_text(key_node, content_bytes).strip("\"'")
                value_text = node_text(value_node, content_bytes).strip("\"'")
                if key_name == "output" and value_text == "export":
                    evidence_id = context.add_evidence(
                        source_file,
                        "nextjs_static_export",
                        node.start_point[0] + 1,
                        node.end_point[0] + 1,
                    )
                    context.architecture_signals.append(
                        ArchitectureSignal(
                            id=create_identifier(
                                "architecture", source_file.id, "static_export"
                            ),
                            project_id=source_file.project_id,
                            kind="static_export",
                            name="Next.js static export",
                            description="Next.js configuration contains the literal output: export setting.",
                            detection="observed",
                            entity_ids=(source_file.id,),
                            evidence_ids=(evidence_id,),
                            limitations=(
                                "Static setting; conditional overrides and runtime configuration are not evaluated.",
                            ),
                        )
                    )

    visit_node(syntax_tree.root_node)

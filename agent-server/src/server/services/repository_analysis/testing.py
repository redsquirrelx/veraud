"""Identify test artifacts and configuration without executing any tests."""

import ast
import posixpath
import re

from .context import AnalysisContext, create_identifier
from .entrypoints import python_import_aliases, resolve_python_name
from .schemas import TestConfiguration

TEST_FRAMEWORKS = {
    "pytest": "pytest",
    "jest": "Jest",
    "vitest": "Vitest",
    "mocha": "Mocha",
    "cypress": "Cypress",
    "@playwright/test": "Playwright",
    "unittest": "unittest",
}


def is_test_file(path: str) -> bool:
    file_name = posixpath.basename(path)
    return (
        file_name == "tests.py"
        or file_name.startswith("test_")
        and path.endswith(".py")
        or file_name.endswith("_test.py")
        or bool(re.search(r"\.(test|spec)\.(js|jsx|ts|tsx|mjs|cjs)$", file_name))
        or any(
            directory in ("tests", "test", "__tests__")
            for directory in path.split("/")[:-1]
        )
        and path.endswith((".py", ".js", ".ts", ".tsx", ".jsx"))
    )


def extract_testing(context: AnalysisContext):
    for project in context.projects:
        source_files = [
            source_file
            for source_file in context.processed_files()
            if source_file.project_id == project.id
        ]
        test_files = [
            source_file
            for source_file in source_files
            if is_test_file(source_file.path)
        ]
        configurations: dict[str, list] = {}
        for source_file in source_files:
            file_name = posixpath.basename(source_file.path)
            configuration = context.configuration.get(source_file.path, {})
            framework = None
            if (
                file_name in ("pytest.ini", "conftest.py")
                or "pytest" in configuration.get("tool", {})
                or "tool:pytest" in configuration
            ):
                framework = "pytest"
            else:
                for prefix, framework_name in (
                    ("jest.config", "Jest"),
                    (".jestrc", "Jest"),
                    ("vitest.config", "Vitest"),
                    ("cypress.config", "Cypress"),
                    ("playwright.config", "Playwright"),
                    (".mocharc", "Mocha"),
                ):
                    if file_name.startswith(prefix):
                        framework = framework_name
                        break
            if file_name == "package.json" and "jest" in configuration:
                framework = "Jest"
            if framework:
                configurations.setdefault(framework, []).append(source_file)
        declared_frameworks = {
            TEST_FRAMEWORKS[dependency.name]
            for dependency in context.dependencies
            if dependency.project_id == project.id
            and dependency.name in TEST_FRAMEWORKS
            and dependency.scope != "transitive"
        }
        unittest_imports = [
            relationship
            for relationship in context.relationships
            if relationship.project_id == project.id
            and relationship.specifier.split(".", 1)[0] == "unittest"
        ]
        uses_unittest_cases = False
        for source_file in test_files:
            syntax_tree = context.python_trees.get(source_file.path)
            if syntax_tree is not None:
                aliases = python_import_aliases(syntax_tree)
                uses_unittest_cases |= any(
                    isinstance(node, ast.ClassDef)
                    and any(
                        resolve_python_name(base, aliases) == "unittest.TestCase"
                        for base in node.bases
                    )
                    for node in ast.walk(syntax_tree)
                )
        if uses_unittest_cases:
            declared_frameworks.add("unittest")
        if any(
            relationship.specifier.startswith("django.test")
            and relationship.source_id in {source_file.id for source_file in test_files}
            for relationship in context.relationships
        ):
            declared_frameworks.add("Django TestCase")
        frameworks = sorted(declared_frameworks | set(configurations)) or (
            [None] if test_files else []
        )
        commands = []
        command_evidence_ids = []
        for source_file in source_files:
            if posixpath.basename(source_file.path) == "package.json":
                for script_name, command in sorted(
                    context.configuration.get(source_file.path, {})
                    .get("scripts", {})
                    .items()
                ):
                    if re.match(r"^test($|[:_-])", script_name) or any(
                        framework.lower() in str(command).lower()
                        for framework in declared_frameworks
                    ):
                        commands.append(f"npm run {script_name}: {command}")
                        command_evidence_ids.append(
                            context.add_evidence(
                                source_file,
                                "test_command",
                                configuration_key=f"scripts.{script_name}",
                            )
                        )
            elif posixpath.basename(source_file.path) in ("Makefile", "makefile"):
                for line_number, line in enumerate(source_file.content.splitlines(), 1):
                    if line.startswith("\t") and re.search(
                        r"\b(pytest|jest|vitest|unittest|playwright|cypress)\b", line
                    ):
                        commands.append(line.strip())
                        command_evidence_ids.append(
                            context.add_evidence(
                                source_file, "test_command", line_number, line_number
                            )
                        )
        for framework in frameworks:
            configuration_files = configurations.get(framework, [])
            evidence_ids = [
                context.add_evidence(source_file, "test_file_convention")
                for source_file in test_files
            ]
            evidence_ids.extend(
                context.add_evidence(source_file, "test_configuration")
                for source_file in configuration_files
            )
            evidence_ids.extend(
                evidence_id
                for dependency in context.dependencies
                if dependency.project_id == project.id
                and TEST_FRAMEWORKS.get(dependency.name) == framework
                for evidence_id in dependency.evidence_ids
            )
            evidence_ids.extend(
                evidence_id
                for relationship in unittest_imports
                for evidence_id in relationship.evidence_ids
            )
            context.testing.append(
                TestConfiguration(
                    id=create_identifier("testing", project.id, framework),
                    project_id=project.id,
                    framework=framework,
                    file_paths=tuple(source_file.path for source_file in test_files),
                    configuration_paths=tuple(
                        source_file.path for source_file in configuration_files
                    ),
                    commands=tuple(sorted(set(commands))),
                    detection="inferred" if framework is None else "observed",
                    evidence_ids=tuple(
                        sorted(set(evidence_ids + command_evidence_ids))
                    ),
                )
            )
